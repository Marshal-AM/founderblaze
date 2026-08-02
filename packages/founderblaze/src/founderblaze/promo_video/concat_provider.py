from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import file_asset, local_path, unwrap_url
from founderblaze.promo_video.ffmpeg_util import resolve_ffmpeg

log = logging.getLogger("founderblaze.promo_video.concat")


class ConcatVideoProvider(SyncProvider):
    """Concatenate one or more segment MP4s into work/promo.mp4."""

    name = "promo-video-concat"

    def __init__(self, *, work_dir: str | None = None) -> None:
        super().__init__()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        dest = work / "promo.mp4"

        paths: list[Path] = []
        for asset in step.inputs or []:
            url = unwrap_url(getattr(asset, "url", None))
            path = local_path(url)
            if path and path.is_file() and path.suffix.lower() == ".mp4":
                paths.append(path)

        if not paths:
            raise RuntimeError("ConcatVideoProvider needs at least one local MP4 input")

        if len(paths) == 1:
            src = paths[0]
            if src.resolve() != dest.resolve():
                dest.write_bytes(src.read_bytes())
        else:
            ffmpeg = resolve_ffmpeg()
            list_path = work / "concat_list.txt"
            lines = []
            for p in paths:
                # ffmpeg concat demuxer: escape single quotes in path
                escaped = p.resolve().as_posix().replace("'", "'\\''")
                lines.append(f"file '{escaped}'")
            list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            cmd = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(dest),
            ]
            log.info("ffmpeg concat segments=%s → %s", len(paths), dest)
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0 or not dest.is_file():
                # Re-encode fallback when stream copy fails across Veo outputs
                cmd_re = [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(dest),
                ]
                proc2 = subprocess.run(cmd_re, capture_output=True, text=True, check=False)
                if proc2.returncode != 0 or not dest.is_file():
                    raise RuntimeError(
                        f"ffmpeg concat failed: {proc.stderr[-500:] or proc2.stderr[-500:]}"
                    )

        if dest.stat().st_size < 1000:
            raise RuntimeError("concat promo.mp4 is missing or too small")

        log.info("concat ready bytes=%s path=%s", dest.stat().st_size, dest)
        step.assets.append(
            file_asset(
                dest,
                media_type="video/mp4",
                metadata={"kind": "promo_video", "segments": len(paths)},
            )
        )
        return step
