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
from founderblaze.core.gemini_retry import generate_content_with_retry

log = logging.getLogger("founderblaze.app_kit.screens")

BOARD_ASPECT_RATIO = "16:9"

_BOARD_VARIANTS = (
    (
        "mobile",
        "phone / mobile app UI kit board",
        "stacked phone layouts, thumb-friendly bottom tabs / stack nav",
    ),
    (
        "desktop",
        "desktop / web app UI kit board",
        "wide layouts with sidebar and/or top nav, denser information hierarchy",
    ),
)


class ScreensProvider(SyncProvider):
    """Generate exactly two 16:9 UI kit boards (mobile + desktop) via Gemini."""

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
        screen_ids = [str(s.get("id") or "") for s in screens]

        model = step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="app-kit-screens-"))
        out_dir = work / "screens"
        out_dir.mkdir(parents=True, exist_ok=True)

        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=self.api_key or os.environ.get("GEMINI_API_KEY"))

        generated = 0
        for i, (viewport, board_label, layout_hint) in enumerate(_BOARD_VARIANTS):
            if i > 0:
                wait_between_steps(f"board-{viewport}")
            nav_hint = str(
                nav.get(viewport)
                or (
                    "bottom tabs + stack"
                    if viewport == "mobile"
                    else "left sidebar + top bar"
                )
            )
            prompt = _board_prompt(
                product_name=self.product_name,
                product_idea=self.product_idea,
                screens=screens,
                viewport=viewport,
                board_label=board_label,
                layout_hint=layout_hint,
                nav_hint=nav_hint,
                palette=palette,
                typography=typography,
                voice=voice,
            )
            log.info(
                "generating UI kit board viewport=%s screens=%s model=%s",
                viewport,
                len(screens),
                model,
            )
            parts: list[Any] = [genai_types.Part.from_text(text=prompt)]
            for img_bytes, mime in ref_images[:4]:
                parts.append(
                    genai_types.Part.from_bytes(data=img_bytes, mime_type=mime)
                )

            resp = generate_content_with_retry(
                lambda parts=parts, model=model: client.models.generate_content(
                    model=model,
                    contents=parts,
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        image_config=genai_types.ImageConfig(
                            aspect_ratio=BOARD_ASPECT_RATIO
                        ),
                    ),
                )
            )
            png = _extract_image_bytes(resp)
            if not png:
                raise RuntimeError(f"no image returned for {viewport} UI kit board")
            fname = "ui-kit-board.png"
            step.assets.append(
                bytes_file_asset(
                    png,
                    suffix=".png",
                    media_type="image/png",
                    work_dir=out_dir / viewport,
                    name=fname,
                    metadata={
                        "kind": "ui_mock",
                        "viewport": viewport,
                        "title": f"{viewport} UI kit board",
                        "zip_path": f"{viewport}/{fname}",
                        "screen_ids": screen_ids,
                        "screen_count": len(screens),
                        "aspect_ratio": BOARD_ASPECT_RATIO,
                    },
                )
            )
            generated += 1

        step.metadata = {
            **(step.metadata or {}),
            "mock_count": generated,
            "screen_count": len(screens),
            "board_count": 2,
        }
        log.info("generated %s UI kit boards for %s screens", generated, len(screens))
        return step


def _board_prompt(
    *,
    product_name: str,
    product_idea: str,
    screens: list[dict[str, Any]],
    viewport: str,
    board_label: str,
    layout_hint: str,
    nav_hint: str,
    palette: dict[str, Any],
    typography: dict[str, Any],
    voice: str,
) -> str:
    palette_s = (
        ", ".join(f"{k}={v}" for k, v in palette.items()) or "cohesive product palette"
    )
    typo_s = (
        f"heading={typography.get('heading')}, body={typography.get('body')}, "
        f"mood={typography.get('mood')}"
    )
    screen_blocks: list[str] = []
    for i, screen in enumerate(screens, start=1):
        key_ui = ", ".join(str(x) for x in (screen.get("key_ui") or [])[:8])
        screen_blocks.append(
            f"{i}. id={screen.get('id')} | title={screen.get('title')}\n"
            f"   purpose: {screen.get('purpose')}\n"
            f"   key_ui: {key_ui}\n"
            f"   nav: {screen.get('nav')}"
        )
    screens_s = "\n".join(screen_blocks)
    cols = 3 if len(screens) >= 5 else 2
    return f"""Create ONE production-quality 16:9 {board_label} — a single image containing ALL of the screens below arranged in a clean labeled grid.

Product: {product_name}
Idea: {product_idea}
Viewport: {viewport}
Layout style: {layout_hint}
Shared navigation pattern: {nav_hint}
Brand palette: {palette_s}
Typography: {typo_s}
Voice: {voice}

Screens to show (every one must appear as its own panel on this board):
{screens_s}

Hard requirements:
- Exactly one 16:9 landscape composition (UI kit / moodboard), not separate images.
- Arrange panels in a neat ~{cols}-column grid with small title labels under each screen panel.
- Each panel is a high-fidelity finished {viewport} UI for THAT screen (real components, spacing, hierarchy, believable content).
- Consistent brand colors/typography across all panels; use brand logo references when provided.
- {layout_hint}.
- No device chrome / bezels / watermarks / unfinished lorem placeholders.
- Look like a top-tier product designer UI kit presentation board.
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
