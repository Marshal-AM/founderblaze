from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import crop_cover
from founderblaze.pitch_deck._assets import (
    assert_slide_count,
    asset_json,
    bytes_file_asset,
    wait_between_steps,
)

log = logging.getLogger("founderblaze.pitch_deck.slides")

# Match Brand Kit banner pattern: Gemini ImageConfig aspect + cover crop.
SLIDE_ASPECT_RATIO = "16:9"
SLIDE_WIDTH = 1920
SLIDE_HEIGHT = 1080


class SlidesProvider(SyncProvider):
    """Generate 6–8 landscape pitch-slide PNGs via Gemini image model."""

    name = "pitch-deck-slides"

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
            supported_modalities=[Modality.IMAGE],
            accepts_chain_input=True,
            supported_inputs=["image", "text"],
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)
        if not step.inputs:
            raise RuntimeError("SlidesProvider needs plan + design (+ brief) assets")

        brief: dict[str, Any] = {}
        design: dict[str, Any] = {}
        plan: dict[str, Any] = {}
        ref_images: list[tuple[bytes, str]] = []

        for asset in step.inputs:
            mt = getattr(asset, "media_type", "") or ""
            meta = dict(getattr(asset, "metadata", None) or {})
            if mt == "application/json":
                data = asset_json(asset)
                kind = meta.get("kind")
                if kind == "pitch_plan" or "slides" in data:
                    plan = data
                if kind == "pitch_design" or (
                    "palette" in data and "typography" in data
                ):
                    design = data
                if kind == "pitch_product_brief" or (
                    "problem" in data and "product_name" in data and "slides" not in data
                ):
                    brief = data
            elif mt.startswith("image/") and meta.get("kind") in {
                "pitch_design_reference",
                "brand_reference",
            }:
                from founderblaze.pitch_deck._assets import read_asset_bytes

                ref_images.append((read_asset_bytes(asset), mt))

        slides = list(plan.get("slides") or [])
        assert_slide_count(len(slides), where="pitch slide plan")

        palette = design.get("palette") if isinstance(design.get("palette"), dict) else {}
        typography = (
            design.get("typography") if isinstance(design.get("typography"), dict) else {}
        )
        layout = design.get("layout") if isinstance(design.get("layout"), dict) else {}
        voice = str(design.get("voice") or "")
        product_name = str(
            plan.get("product_name")
            or brief.get("product_name")
            or design.get("product_name")
            or "Product"
        )
        ask = str(plan.get("funding_ask") or self.funding_ask or "").strip()

        model = step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="pitch-deck-slides-"))
        out_dir = work / "slides"
        out_dir.mkdir(parents=True, exist_ok=True)

        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=self.api_key or os.environ.get("GEMINI_API_KEY"))

        generated = 0
        for i, slide in enumerate(slides):
            if i > 0:
                wait_between_steps(str(slide.get("id") or i))
            sid = str(slide.get("id") or f"slide-{i + 1}")
            prompt = _slide_prompt(
                product_name=product_name,
                product_url=self.product_url,
                funding_ask=ask,
                slide=slide,
                index=i + 1,
                total=len(slides),
                palette=palette,
                typography=typography,
                layout=layout,
                voice=voice,
                one_liner=str(brief.get("one_liner") or ""),
            )
            log.info("generating pitch slide=%s model=%s", sid, model)
            parts: list[Any] = [genai_types.Part.from_text(text=prompt)]
            for img_bytes, mime in ref_images[:4]:
                parts.append(
                    genai_types.Part.from_bytes(data=img_bytes, mime_type=mime)
                )

            resp = client.models.generate_content(
                model=model,
                contents=parts,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=genai_types.ImageConfig(
                        aspect_ratio=SLIDE_ASPECT_RATIO
                    ),
                ),
            )
            png = _extract_image_bytes(resp)
            if not png:
                raise RuntimeError(f"no image returned for slide={sid}")
            # Force consistent landscape slide canvas (Gemini can still drift slightly).
            png = crop_cover(png, SLIDE_WIDTH, SLIDE_HEIGHT)
            fname = f"{i + 1:02d}-{sid}.png"
            step.assets.append(
                bytes_file_asset(
                    png,
                    suffix=".png",
                    media_type="image/png",
                    work_dir=out_dir,
                    name=fname,
                    metadata={
                        "kind": "pitch_slide",
                        "slide_id": sid,
                        "order": i,
                        "headline": slide.get("headline"),
                        "role": slide.get("role"),
                        "aspect_ratio": SLIDE_ASPECT_RATIO,
                        "width": SLIDE_WIDTH,
                        "height": SLIDE_HEIGHT,
                    },
                )
            )
            generated += 1

        assert_slide_count(generated, where="pitch slide generation")
        step.metadata = {
            **(step.metadata or {}),
            "slide_count": generated,
            "product_name": product_name,
        }
        log.info("generated %s pitch slide images", generated)
        return step


def _slide_prompt(
    *,
    product_name: str,
    product_url: str,
    funding_ask: str,
    slide: dict[str, Any],
    index: int,
    total: int,
    palette: dict[str, Any],
    typography: dict[str, Any],
    layout: dict[str, Any],
    voice: str,
    one_liner: str,
) -> str:
    bullets = "\n".join(f"- {b}" for b in (slide.get("bullets") or [])[:6])
    palette_s = ", ".join(f"{k}={v}" for k, v in palette.items()) or "cohesive brand palette"
    typo_s = (
        f"heading={typography.get('heading')}, body={typography.get('body')}, "
        f"mood={typography.get('mood')}"
    )
    layout_s = (
        f"density={layout.get('density')}, corners={layout.get('corner_radius')}, "
        f"imagery={layout.get('imagery_style')}"
    )
    ask_note = ""
    role = str(slide.get("role") or "").lower()
    if "ask" in role or "ask" in str(slide.get("id") or "").lower():
        ask_note = f"\nThis is the ASK slide — display the funding ask prominently and exactly: {funding_ask}"

    return f"""Design a PRODUCTION-QUALITY investor pitch deck SLIDE.

Canvas: landscape widescreen {SLIDE_ASPECT_RATIO} (exactly {SLIDE_WIDTH}x{SLIDE_HEIGHT} presentation frame). NOT square. NOT 1:1.

Product: {product_name}
URL: {product_url}
One-liner: {one_liner or "n/a"}
Funding ask: {funding_ask}
Slide {index} of {total}
Slide id: {slide.get('id')}
Role: {slide.get('role')}
Headline: {slide.get('headline')}
Bullets to include:
{bullets or "- (headline-led visual)"}
Visual direction: {slide.get('visual_direction') or "clean investor slide"}
Brand palette: {palette_s}
Typography: {typo_s}
Layout: {layout_s}
Voice: {voice}
{ask_note}

Hard requirements:
- Wide landscape 16:9 slide like Keynote / Google Slides / Pitch.com — horizontal rectangle, full-bleed.
- Match the product brand colors/typography/layout density — NOT generic purple AI gradients unless the brand is purple.
- Crisp hierarchy: big headline, readable bullets, generous margins, professional fundraising aesthetic.
- No watermark, no fake browser UI, no "Lorem ipsum", no tiny unreadable text.
- Believable founder-grade deck page that could be shown to investors.
"""


def _extract_image_bytes(resp: Any) -> bytes | None:
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            if data is None:
                continue
            if isinstance(data, str):
                return base64.b64decode(data)
            if isinstance(data, (bytes, bytearray)):
                return bytes(data)
    return None
