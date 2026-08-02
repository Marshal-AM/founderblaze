from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.pitch_deck._assets import json_file_asset
from founderblaze.promo_video.gemini_chat import gemini_grounded_json

log = logging.getLogger("founderblaze.pitch_deck.research")


class ProductResearchProvider(SyncProvider):
    """Gemini + Google Search grounding → product brief for the pitch deck."""

    name = "pitch-deck-research"

    def __init__(
        self,
        *,
        product_url: str,
        funding_ask: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_url = product_url
        self.funding_ask = funding_ask
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        url = (self.product_url or "").strip()
        ask = (self.funding_ask or "").strip()
        if not url:
            raise RuntimeError("product_url is required")
        if not ask:
            raise RuntimeError("funding_ask is required")

        host = (urlparse(url).hostname or "").replace("www.", "")
        brief = gemini_grounded_json(
            f"""Research the product at this URL for an investor pitch deck.
Use Google Search grounding. Prefer facts about THIS product/site.

Product URL: {url}
Site host: {host}
Funding ask (use exactly in later slides; do not invent a different amount): {ask}

Return a concise product brief as JSON only (no markdown fences):
{{
  "product_name": string,
  "one_liner": string,
  "value_prop": string,
  "audience": string,
  "problem": string,
  "solution": string,
  "differentiators": string[],
  "key_features": string[],
  "proof_points": string[],
  "market": string,
  "business_model": string,
  "competitors": string[],
  "gtm": string,
  "tone_cues": string[],
  "brand_personality": string,
  "unknowns": string[],
  "sources_note": string
}}

Rules:
- differentiators / key_features / proof_points / competitors: 2–8 items when known.
- Do NOT invent fake traction, revenue, logos, or customers. Put gaps in unknowns.
- market / business_model / gtm: best-effort from public info; say "unknown" if thin.
- funding_ask will be applied separately; do not invent a different raise amount.
""",
            model=model,
            api_key=self.api_key,
            system=(
                "You are a product and market researcher for an investor pitch deck. "
                "Use Google Search grounding. Return JSON only. Never invent metrics."
            ),
        )

        name = str(brief.get("product_name") or "").strip() or host or "Product"
        brief["product_name"] = name
        brief["product_url"] = url
        brief["funding_ask"] = ask
        brief["model"] = model
        for key, default in (
            ("one_liner", ""),
            ("value_prop", ""),
            ("audience", ""),
            ("problem", ""),
            ("solution", ""),
            ("differentiators", []),
            ("key_features", []),
            ("proof_points", []),
            ("market", ""),
            ("business_model", ""),
            ("competitors", []),
            ("gtm", ""),
            ("tone_cues", []),
            ("brand_personality", ""),
            ("unknowns", []),
            ("sources_note", ""),
        ):
            brief.setdefault(key, default)

        log.info(
            "pitch product brief ready name=%s features=%s",
            name,
            len(brief.get("key_features") or []),
        )
        step.assets.append(
            json_file_asset(
                brief,
                work_dir=Path(self.work_dir or "."),
                name="product_brief",
                metadata={"kind": "pitch_product_brief"},
            )
        )
        return step
