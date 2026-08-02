from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import json_file_asset
from founderblaze.promo_video.gemini_chat import gemini_grounded_json

log = logging.getLogger("founderblaze.promo_video.research")


class ProductResearchProvider(SyncProvider):
    """Gemini + Google Search grounding → product brief for the promo ad."""

    name = "promo-video-research"

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
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        url = (self.product_url or "").strip()
        if not url:
            raise RuntimeError("product_url is required")

        host = (urlparse(url).hostname or "").replace("www.", "")
        brief = gemini_grounded_json(
            f"""Research the product at this URL using Google Search grounding.
Product URL: {url}
Site host: {host}

Return a concise product brief as JSON only (no markdown fences):
{{
  "product_name": string,
  "one_liner": string,
  "value_prop": string,
  "audience": string,
  "problem": string,
  "differentiators": string[],
  "tone_cues": string[],
  "key_features": string[],
  "proof_points": string[],
  "brand_personality": string,
  "sources_note": string
}}

Rules:
- Prefer facts grounded in search results about THIS product/site.
- differentiators / key_features / proof_points: 3–8 specific items each when known.
- tone_cues: short adjectives that match the brand vibe.
- sources_note: brief note on what you found (or that coverage was thin).
- Do not invent fake pricing or fake customer logos.
""",
            model=model,
            api_key=self.api_key,
            system=(
                "You are a product researcher for a short promo video. "
                "Use Google Search grounding. Return JSON only."
            ),
        )

        name = str(brief.get("product_name") or "").strip() or host or "Product"
        brief["product_name"] = name
        brief["product_url"] = url
        brief["model"] = model
        brief.setdefault("one_liner", "")
        brief.setdefault("value_prop", "")
        brief.setdefault("audience", "")
        brief.setdefault("problem", "")
        brief.setdefault("differentiators", [])
        brief.setdefault("tone_cues", [])
        brief.setdefault("key_features", [])
        brief.setdefault("proof_points", [])
        brief.setdefault("brand_personality", "")
        brief.setdefault("sources_note", "")

        log.info(
            "product brief ready name=%s features=%s",
            name,
            len(brief.get("key_features") or []),
        )
        step.assets.append(
            json_file_asset(
                brief,
                work_dir=Path(self.work_dir or "."),
                name="product_brief",
                metadata={"kind": "promo_product_brief"},
            )
        )
        return step
