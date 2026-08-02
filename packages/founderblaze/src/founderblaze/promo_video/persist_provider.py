from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import file_asset, unwrap_url

log = logging.getLogger("founderblaze.promo_video.persist")


class PersistVideoProvider(SyncProvider):
    """Download Veo Files API URL → local promo.mp4 file:// asset."""

    name = "promo-video-persist"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        # When used per-segment, work_dir is seg_N/; final name still promo.mp4
        dest = work / "promo.mp4"

        source_url = _find_video_url(step.inputs)
        if not source_url:
            raise RuntimeError("No video URL from prior Veo step")

        if source_url.startswith("file:"):
            from urllib.parse import unquote, urlparse

            parsed = urlparse(source_url)
            src = Path(unquote(parsed.path))
            if src.as_posix().startswith("/") and len(src.as_posix()) > 2 and src.as_posix()[2] == ":":
                src = Path(src.as_posix()[1:])
            if not src.is_file():
                raise RuntimeError(f"Local Veo file missing: {src}")
            if src.resolve() != dest.resolve():
                dest.write_bytes(src.read_bytes())
        elif Path(source_url).is_file():
            dest.write_bytes(Path(source_url).read_bytes())
        elif source_url.startswith("http://") or source_url.startswith("https://"):
            req = urllib.request.Request(
                source_url,
                headers={"x-goog-api-key": self.api_key} if self.api_key else {},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                dest.write_bytes(resp.read())
        else:
            raise RuntimeError(f"Unsupported Veo asset URL: {source_url[:120]}")

        if not dest.is_file() or dest.stat().st_size < 1000:
            raise RuntimeError("Persisted promo.mp4 is missing or too small")

        log.info("persisted promo video bytes=%s path=%s", dest.stat().st_size, dest)
        step.assets.append(
            file_asset(
                dest,
                media_type="video/mp4",
                metadata={
                    "kind": "promo_video",
                    "source_url": source_url,
                },
            )
        )
        return step


def _find_video_url(inputs: list) -> str:
    for asset in inputs or []:
        url = unwrap_url(getattr(asset, "url", None))
        media = getattr(asset, "media_type", "") or ""
        if "video" in media or url.endswith(".mp4") or ".mp4?" in url or "/files/" in url:
            return url
    # Fallback: first asset with any URL
    for asset in inputs or []:
        url = unwrap_url(getattr(asset, "url", None))
        if url:
            return url
    return ""
