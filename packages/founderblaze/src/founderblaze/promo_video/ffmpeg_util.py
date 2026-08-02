"""Resolve an ffmpeg binary (PATH or imageio-ffmpeg)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        getter = getattr(imageio_ffmpeg, "get_ffmpeg_exe", None)
        if callable(getter):
            path = getter()
            if path and Path(path).is_file():
                return str(path)
    except Exception:  # noqa: BLE001
        pass
    names = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg",)
    for root in __import__("sys").path:
        bin_dir = Path(root) / "imageio_ffmpeg" / "binaries"
        if not bin_dir.is_dir():
            continue
        for name in names:
            candidate = bin_dir / name
            if candidate.is_file():
                return str(candidate)
        for p in sorted(bin_dir.glob("ffmpeg*")):
            if p.is_file():
                return str(p)
    raise RuntimeError(
        "ffmpeg not found on PATH and no imageio-ffmpeg binary is available "
        "(pip install imageio-ffmpeg)"
    )
