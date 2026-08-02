from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import (
    asset_json,
    bytes_file_asset,
    render_palette_png,
    render_typography_png,
)

log = logging.getLogger("founderblaze.brand_kit.visuals")


class VisualsProvider(SyncProvider):
    """Render palette + typography specimen PNGs."""

    name = "brand-kit-visuals"

    def __init__(self, *, brand_name: str, work_dir: str | None = None) -> None:
        super().__init__()
        self.brand_name = brand_name
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("VisualsProvider needs palette + fonts assets")

        palette_payload = {}
        fonts_summary = {}
        for asset in step.inputs:
            mt = getattr(asset, "media_type", "") or ""
            if mt != "application/json":
                continue
            data = asset_json(asset)
            if "palette" in data:
                palette_payload = data
            if "css_url" in data or "heading_regular_path" in data:
                fonts_summary = data

        palette = palette_payload.get("palette") or {
            "primary": "#111111",
            "secondary": "#666666",
            "accent": "#222222",
            "light": "#F5F5F5",
            "dark": "#0A0A0A",
        }
        typography = (
            fonts_summary.get("typography")
            or palette_payload.get("typography")
            or {}
        )

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-visuals-"))
        work.mkdir(parents=True, exist_ok=True)

        heading_bytes = _read_optional(fonts_summary.get("heading_regular_path"))
        body_bytes = _read_optional(fonts_summary.get("body_regular_path"))

        colors_png = render_palette_png(palette, brand_name=self.brand_name)
        type_png = render_typography_png(
            typography=typography,
            brand_name=self.brand_name,
            heading_font_bytes=heading_bytes,
            body_font_bytes=body_bytes,
            work_dir=work,
        )

        step.assets.append(
            bytes_file_asset(
                colors_png,
                suffix=".png",
                media_type="image/png",
                work_dir=work,
                name="brand-colors.png",
                metadata={"kind": "visual", "zip_path": "brand-colors.png"},
            )
        )
        step.assets.append(
            bytes_file_asset(
                type_png,
                suffix=".png",
                media_type="image/png",
                work_dir=work,
                name="typography-specimen.png",
                metadata={"kind": "visual", "zip_path": "typography-specimen.png"},
            )
        )
        log.info("visuals rendered brand=%s", self.brand_name)
        return step


def _read_optional(path: str | None) -> bytes | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    return p.read_bytes()
