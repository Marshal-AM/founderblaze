from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.app_kit._assets import (
    asset_json,
    bytes_file_asset,
    read_asset_bytes,
    wait_between_steps,
)

log = logging.getLogger("founderblaze.app_kit.screens")


class ScreensProvider(SyncProvider):
    """Generate desktop + mobile UI mock PNGs for every planned screen via Gemini."""

    name = "app-kit-screens"

    def __init__(
        self,
        *,
        product_name: str,
        product_idea: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.product_idea = product_idea
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
            raise RuntimeError("ScreensProvider needs plan + brand context assets")

        plan: dict[str, Any] = {}
        brand: dict[str, Any] = {}
        ref_images: list[tuple[bytes, str]] = []

        for asset in step.inputs:
            mt = getattr(asset, "media_type", "") or ""
            meta = dict(getattr(asset, "metadata", None) or {})
            if mt == "application/json":
                data = asset_json(asset)
                if "screens" in data and "palette" not in data:
                    plan = data
                if "palette" in data or meta.get("kind") == "brand_context":
                    brand = data
            elif mt.startswith("image/") and meta.get("kind") == "brand_reference":
                ref_images.append((read_asset_bytes(asset), mt))

        screens = list(plan.get("screens") or [])
        if len(screens) < 4:
            raise RuntimeError("screen plan missing or too short")

        palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
        typography = (
            brand.get("typography") if isinstance(brand.get("typography"), dict) else {}
        )
        voice = str(brand.get("voice") or "")
        nav = plan.get("nav_pattern") if isinstance(plan.get("nav_pattern"), dict) else {}

        model = step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="app-kit-screens-"))
        out_dir = work / "screens"
        out_dir.mkdir(parents=True, exist_ok=True)

        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=self.api_key or os.environ.get("GEMINI_API_KEY"))

        variants = (
            ("desktop", "1440x900 desktop web app UI, wide layout", nav.get("desktop")),
            ("mobile", "390x844 mobile app UI, phone layout", nav.get("mobile")),
        )

        generated = 0
        first = True
        for screen in screens:
            sid = str(screen.get("id") or "screen")
            for viewport, viewport_hint, nav_hint in variants:
                if not first:
                    wait_between_steps(f"{sid}-{viewport}")
                first = False
                prompt = _screen_prompt(
                    product_name=self.product_name,
                    product_idea=self.product_idea,
                    screen=screen,
                    viewport=viewport,
                    viewport_hint=viewport_hint,
                    nav_hint=str(nav_hint or ""),
                    palette=palette,
                    typography=typography,
                    voice=voice,
                )
                log.info(
                    "generating UI mock screen=%s viewport=%s model=%s",
                    sid,
                    viewport,
                    model,
                )
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
                    ),
                )
                png = _extract_image_bytes(resp)
                if not png:
                    raise RuntimeError(
                        f"no image returned for screen={sid} viewport={viewport}"
                    )
                fname = f"{sid}-{viewport}.png"
                step.assets.append(
                    bytes_file_asset(
                        png,
                        suffix=".png",
                        media_type="image/png",
                        work_dir=out_dir,
                        name=fname,
                        metadata={
                            "kind": "ui_mock",
                            "screen_id": sid,
                            "viewport": viewport,
                            "title": screen.get("title"),
                            "zip_path": f"{viewport}/{fname}",
                        },
                    )
                )
                generated += 1

        step.metadata = {
            **(step.metadata or {}),
            "mock_count": generated,
            "screen_count": len(screens),
        }
        log.info("generated %s UI mock images", generated)
        return step


def _screen_prompt(
    *,
    product_name: str,
    product_idea: str,
    screen: dict[str, Any],
    viewport: str,
    viewport_hint: str,
    nav_hint: str,
    palette: dict[str, Any],
    typography: dict[str, Any],
    voice: str,
) -> str:
    key_ui = ", ".join(str(x) for x in (screen.get("key_ui") or [])[:8])
    palette_s = ", ".join(f"{k}={v}" for k, v in palette.items()) or "cohesive product palette"
    typo_s = (
        f"heading={typography.get('heading')}, body={typography.get('body')}, "
        f"mood={typography.get('mood')}"
    )
    return f"""Design a PRODUCTION-QUALITY {viewport_hint} mock for a real shipping product — not a wireframe.

Product: {product_name}
Idea: {product_idea}
Screen id: {screen.get('id')}
Screen title: {screen.get('title')}
Purpose: {screen.get('purpose')}
Key UI to include: {key_ui}
Navigation: {screen.get('nav')} | Pattern ({viewport}): {nav_hint}
Brand palette: {palette_s}
Typography: {typo_s}
Voice: {voice}

Hard requirements:
- High-fidelity finished UI (real components, spacing, hierarchy, believable content).
- Consistent brand colors/typography across the suite; use brand logo references when provided.
- {viewport.upper()} layout must be distinct: desktop denser with sidebar/top-nav; mobile stacked with thumb-friendly nav.
- Full-bleed app UI filling the frame. No device chrome, no bezel mockup, no watermark, no "Lorem" placeholders that look unfinished.
- Look like a top-tier product designer / UI kit screenshot, not a sketch.
- Show the "{screen.get('title')}" screen clearly as the primary view.
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
