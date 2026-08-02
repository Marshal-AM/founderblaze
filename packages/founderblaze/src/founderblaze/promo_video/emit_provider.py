from __future__ import annotations

import logging
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import file_asset

log = logging.getLogger("founderblaze.promo_video.emit")


class EmitFinalVideoProvider(SyncProvider):
    """Re-emit local work/promo.mp4 as the sole pipeline asset (for B2 sink)."""

    name = "promo-video-emit"

    def __init__(self, *, work_dir: str | None = None) -> None:
        super().__init__()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.VIDEO])

    def generate(self, step, config=None):  # noqa: ANN001
        path = Path(self.work_dir or ".") / "promo.mp4"
        if not path.is_file() or path.stat().st_size < 1000:
            raise RuntimeError(f"final promo.mp4 missing: {path}")
        log.info("emit final video bytes=%s path=%s", path.stat().st_size, path)
        step.assets.append(
            file_asset(
                path,
                media_type="video/mp4",
                metadata={"kind": "promo_video"},
            )
        )
        return step
