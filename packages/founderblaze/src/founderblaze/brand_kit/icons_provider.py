from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import (
    bytes_file_asset,
    chosen_logo_assets,
    make_favicon_ico,
    read_asset_bytes,
    resize_logo_png,
)

log = logging.getLogger("founderblaze.brand_kit.icons")

ICON_SIZES = (
    (16, "favicon-16x16.png"),
    (32, "favicon-32x32.png"),
    (48, "favicon-48x48.png"),
    (180, "apple-touch-icon.png"),
    (192, "android-chrome-192x192.png"),
    (512, "app-icon-512x512.png"),
    (1024, "app-icon-1024x1024.png"),
)


class IconsProvider(SyncProvider):
    """Resize chosen logo into favicon / app icon set."""

    name = "brand-kit-icons"

    def __init__(self, *, pick: int = 0, work_dir: str | None = None) -> None:
        super().__init__()
        self.pick = pick
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("IconsProvider needs logo step assets")
        chosen, _ = chosen_logo_assets(list(step.inputs), self.pick)
        logo_bytes = read_asset_bytes(chosen)
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-icons-"))
        work.mkdir(parents=True, exist_ok=True)

        png_sizes: dict[int, bytes] = {}
        for size, name in ICON_SIZES:
            buf = resize_logo_png(logo_bytes, size)
            png_sizes[size] = buf
            step.assets.append(
                bytes_file_asset(
                    buf,
                    suffix=".png",
                    media_type="image/png",
                    work_dir=work,
                    name=name,
                    metadata={"kind": "icon", "zip_path": f"assets/{name}"},
                )
            )

        ico = make_favicon_ico(png_sizes)
        step.assets.append(
            bytes_file_asset(
                ico,
                suffix=".ico",
                media_type="image/x-icon",
                work_dir=work,
                name="favicon.ico",
                metadata={"kind": "icon", "zip_path": "assets/favicon.ico"},
            )
        )
        log.info("icons rendered count=%s", len(step.assets))
        return step
