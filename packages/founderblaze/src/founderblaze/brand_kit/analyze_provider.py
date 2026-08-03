from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from founderblaze.brand_kit._fonts_catalog import (
    BODY_FONTS,
    HEADING_FONTS,
    canonicalize_body_font,
    canonicalize_heading_font,
)
from founderblaze.brand_kit._imaging import json_file_asset
from founderblaze.core.gemini_retry import chat_with_retry

log = logging.getLogger("founderblaze.brand_kit.analyze")


class AnalyzeProvider(SyncProvider):
    """Gemini brand analyst via genblaze_google.chat."""

    name = "brand-kit-analyze"

    def __init__(
        self,
        *,
        brand_name: str,
        concept_count: int = 3,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.brand_name = brand_name
        self.concept_count = concept_count
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)
        description = step.prompt or ""
        heading_list = ", ".join(HEADING_FONTS)
        body_list = ", ".join(BODY_FONTS)
        prompt = f"""You are a senior brand designer analyzing a brief to brief logo and typography generation models.

Brand name: "{self.brand_name}"
Brand brief:
\"\"\"{description}\"\"\"

Produce exactly {self.concept_count} distinct logo concept angles tailored to this brand, plus one heading/body font pairing.

Rules for concepts:
- Each concept must feel specific to THIS brand — not generic stock logo recipes.
- Vary the approaches (e.g. wordmark, symbol mark, monogram, emblem, pictorial, badge) but only when they fit the brief.
- id: short kebab-case label (e.g. "wordmark", "flame-mark", "initials-badge").
- needsText: true only if the rendered logo must include readable brand name / initials as lettering in the image; false for pure icon/symbol marks.
- style: one dense visual direction sentence for an image model (flat vector, white background implied later). Mention composition, geometry, and brand-relevant motifs. Do NOT include the brand name string unless needsText is true and lettering is the point.
- Prefer flat vector / logo-ready language. Avoid photo-real / 3D / watermark language.

Rules for typography:
- heading MUST be one of: {heading_list}
- body MUST be one of: {body_list}
- Match the brand personality. Prefer purposeful contrast. Avoid the same family for both unless mono branding truly fits.
- mood: one short kebab-case mood label for the pairing.

Return ONLY JSON:
{{
  "concepts": [{{"id":"...","needsText":true,"style":"..."}}],
  "typography": {{"heading":"...","body":"...","mood":"..."}}
}}"""

        model = step.model or "gemini-2.0-flash"
        log.info("analyzing brand brief model=%s", model)
        resp = chat_with_retry(model, prompt=prompt)
        text = getattr(resp, "text", None) or str(resp)
        analysis = _parse_analysis(text, count=self.concept_count)
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-analyze-"))
        work.mkdir(parents=True, exist_ok=True)
        step.assets.append(
            json_file_asset(
                analysis,
                work_dir=work,
                name="analysis.json",
                metadata={"kind": "analysis"},
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "brand_name": self.brand_name,
            "concept_count": len(analysis.get("concepts") or []),
        }
        return step


def _slugify_id(value: str) -> str:
    s = value.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return (s[:40] if s else "concept")


def _parse_analysis(text: str, *, count: int) -> dict[str, Any]:
    raw = text.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fence:
            parsed = json.loads(fence.group(1).strip())
        else:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0 or end <= start:
                raise ValueError(f"Brand analyst returned non-JSON: {raw[:400]}")
            parsed = json.loads(raw[start : end + 1])

    concepts_in = list(parsed.get("concepts") or [])[:count]
    seen: set[str] = set()
    concepts = []
    for i, c in enumerate(concepts_in):
        cid = _slugify_id(str(c.get("id") or f"concept-{i+1}"))
        if cid in seen:
            cid = f"{cid}-{i+1}"
        seen.add(cid)
        concepts.append(
            {
                "id": cid,
                "needsText": bool(c.get("needsText")),
                "style": str(c.get("style") or "").strip(),
            }
        )
    if len(concepts) < 2:
        raise ValueError("Brand analyst returned fewer than 2 concepts")

    typo = parsed.get("typography") or {}
    return {
        "concepts": concepts,
        "typography": {
            "heading": canonicalize_heading_font(str(typo.get("heading") or "")),
            "body": canonicalize_body_font(str(typo.get("body") or "")),
            "mood": str(typo.get("mood") or "modern").strip(),
        },
    }
