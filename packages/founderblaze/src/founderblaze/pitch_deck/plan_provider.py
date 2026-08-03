from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from founderblaze.core.gemini_retry import chat_with_retry
from founderblaze.pitch_deck._assets import (
    MAX_SLIDES,
    MIN_SLIDES,
    assert_slide_count,
    asset_json,
    json_file_asset,
)

log = logging.getLogger("founderblaze.pitch_deck.plan")


class PlanDeckProvider(SyncProvider):
    """Gemini TEXT: plan exactly 6–8 investor pitch slides."""

    name = "pitch-deck-plan"

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
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
            supported_inputs=["text"],
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)

        brief: dict[str, Any] = {}
        design: dict[str, Any] = {}
        for asset in step.inputs or []:
            meta = dict(getattr(asset, "metadata", None) or {})
            data = asset_json(asset)
            kind = meta.get("kind")
            if kind == "pitch_product_brief" or (
                not brief and "product_name" in data and "problem" in data
            ):
                brief = data
            if kind == "pitch_design" or (
                not design and "palette" in data and "typography" in data
            ):
                design = data

        if not brief:
            raise RuntimeError("PlanDeckProvider needs pitch_product_brief input")

        product_name = str(brief.get("product_name") or "Product")
        ask = (self.funding_ask or brief.get("funding_ask") or "").strip()
        brief_json = json.dumps(brief, indent=2)[:6000]
        design_voice = str(design.get("voice") or brief.get("brand_personality") or "")

        prompt = f"""You are a startup fundraising advisor planning a SHORT investor pitch deck.

Product URL: {self.product_url}
Product name: {product_name}
Funding ask (MUST appear on the Ask slide exactly): {ask}
Design voice: {design_voice}

Product research JSON:
{brief_json}

HARD CONSTRAINT — slide count:
- You MUST return between {MIN_SLIDES} and {MAX_SLIDES} slides inclusive.
- Never fewer than {MIN_SLIDES}. Never more than {MAX_SLIDES}.

Typical structure (adapt to the product; drop/merge as needed to stay in range):
1. Title / company
2. Problem
3. Solution
4. Product / how it works
5. Market opportunity
6. The Ask (funding) — REQUIRED
Optional extras if space allows (still ≤ {MAX_SLIDES}): business model, GTM/traction, competition, closing vision.

Rules:
- Every slide must be specific to THIS product.
- Do NOT invent fake traction, revenue, logos, or customers. If unknown, write honest "early-stage / building" framing.
- id: short kebab-case unique id.
- headline: short slide headline.
- bullets: 2–5 concise bullet points for on-slide copy.
- visual_direction: one sentence for the image model (layout + imagery).
- The Ask slide must include the exact funding ask: {ask}

Return ONLY JSON:
{{
  "product_name": "{product_name}",
  "funding_ask": "{ask}",
  "slide_count": {MIN_SLIDES},
  "slides": [
    {{
      "id": "title",
      "role": "title",
      "headline": "...",
      "bullets": ["...", "..."],
      "visual_direction": "..."
    }}
  ]
}}"""

        model = step.model or "gemini-2.5-flash"
        log.info("planning pitch deck model=%s product=%s", model, product_name)
        resp = chat_with_retry(model, prompt=prompt, api_key=self.api_key or None)
        text = getattr(resp, "text", None) or str(resp)
        plan = _parse_plan(text)
        slides = list(plan.get("slides") or [])
        assert_slide_count(len(slides), where="pitch plan")

        plan["product_name"] = product_name
        plan["funding_ask"] = ask
        plan["product_url"] = self.product_url
        plan["slide_count"] = len(slides)

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="pitch-deck-plan-"))
        work.mkdir(parents=True, exist_ok=True)
        step.assets.append(
            json_file_asset(
                plan,
                work_dir=work,
                name="pitch-plan.json",
                metadata={"kind": "pitch_plan"},
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "product_name": product_name,
            "slide_count": len(slides),
        }
        return step


def _parse_plan(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise RuntimeError("pitch plan response was not valid JSON") from None
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise RuntimeError("pitch plan JSON must be an object")
    slides = data.get("slides")
    if not isinstance(slides, list):
        raise RuntimeError("pitch plan missing slides array")
    cleaned = []
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"slide-{i + 1}").strip()
        cleaned.append(
            {
                "id": sid,
                "role": str(s.get("role") or sid),
                "headline": str(s.get("headline") or sid),
                "bullets": [str(x) for x in (s.get("bullets") or [])[:6]],
                "visual_direction": str(s.get("visual_direction") or ""),
            }
        )
    data["slides"] = cleaned
    return data
