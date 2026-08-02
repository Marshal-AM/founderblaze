from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.pitch_deck._assets import asset_json, json_file_asset
from founderblaze.promo_video.gemini_chat import gemini_grounded_json

log = logging.getLogger("founderblaze.pitch_deck.design")


class DesignLanguageProvider(SyncProvider):
    """Extract visual design language from the product URL for slide styling."""

    name = "pitch-deck-design"

    def __init__(
        self,
        *,
        product_url: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_url = product_url
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
            supported_inputs=["text"],
        )

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        url = (self.product_url or "").strip()
        if not url:
            raise RuntimeError("product_url is required")

        brief: dict[str, Any] = {}
        for asset in step.inputs or []:
            meta = dict(getattr(asset, "metadata", None) or {})
            if meta.get("kind") == "pitch_product_brief":
                brief = asset_json(asset)
                break
            data = asset_json(asset) if (getattr(asset, "media_type", "") or "") == "application/json" else {}
            if data.get("product_name") and not brief:
                brief = data

        host = (urlparse(url).hostname or "").replace("www.", "")
        product_name = str(brief.get("product_name") or host or "Product")
        tone = ", ".join(str(x) for x in (brief.get("tone_cues") or [])[:6])
        personality = str(brief.get("brand_personality") or "")

        design = gemini_grounded_json(
            f"""Infer the visual design language of the product website for a matching pitch deck.
Use Google Search grounding and public knowledge about this brand/site.

Product URL: {url}
Product name: {product_name}
Known tone cues: {tone or "n/a"}
Brand personality: {personality or "n/a"}

Return JSON only (no markdown fences):
{{
  "palette": {{
    "background": "#hex",
    "surface": "#hex",
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "text": "#hex",
    "muted_text": "#hex"
  }},
  "typography": {{
    "heading": "font family vibe e.g. geometric sans",
    "body": "font family vibe",
    "mood": "short mood phrase"
  }},
  "layout": {{
    "density": "airy|balanced|dense",
    "corner_radius": "sharp|soft|pill",
    "imagery_style": "product screenshots|illustrations|gradients|photo|minimal type"
  }},
  "voice": "2–4 adjectives for slide copy tone",
  "do": string[],
  "dont": string[],
  "notes": string
}}

Rules:
- Hex colors must be plausible for THIS brand (not generic purple AI defaults unless the brand is purple).
- Match the live product site aesthetic as closely as public info allows.
- do/dont: 2–5 slide design rules each.
""",
            model=model,
            api_key=self.api_key,
            system=(
                "You are a brand designer extracting design tokens for investor slides. "
                "Use Google Search grounding. Return JSON only."
            ),
        )

        palette = design.get("palette") if isinstance(design.get("palette"), dict) else {}
        typography = (
            design.get("typography") if isinstance(design.get("typography"), dict) else {}
        )
        layout = design.get("layout") if isinstance(design.get("layout"), dict) else {}
        design["product_name"] = product_name
        design["product_url"] = url
        design["palette"] = {
            "background": palette.get("background") or "#0B0F14",
            "surface": palette.get("surface") or "#151B24",
            "primary": palette.get("primary") or "#3B82F6",
            "secondary": palette.get("secondary") or "#64748B",
            "accent": palette.get("accent") or "#22D3EE",
            "text": palette.get("text") or "#F8FAFC",
            "muted_text": palette.get("muted_text") or "#94A3B8",
        }
        design["typography"] = {
            "heading": typography.get("heading") or "modern sans",
            "body": typography.get("body") or "clean sans",
            "mood": typography.get("mood") or "confident",
        }
        design["layout"] = {
            "density": layout.get("density") or "balanced",
            "corner_radius": layout.get("corner_radius") or "soft",
            "imagery_style": layout.get("imagery_style") or "minimal type",
        }
        design.setdefault("voice", personality or "clear, confident")
        design.setdefault("do", [])
        design.setdefault("dont", [])
        design.setdefault("notes", "")

        log.info("pitch design language ready product=%s", product_name)
        step.assets.append(
            json_file_asset(
                design,
                work_dir=Path(self.work_dir or "."),
                name="design_language",
                metadata={"kind": "pitch_design"},
            )
        )
        return step
