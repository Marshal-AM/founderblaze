"""Resolve an ffmpeg binary without requiring a system install."""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


def _ensure_on_path(bin_dir: Path) -> None:
    prefix = str(bin_dir)
    path = os.environ.get("PATH", "")
    if prefix and prefix not in path.split(os.pathsep):
        os.environ["PATH"] = prefix + os.pathsep + path


def _from_imageio_api() -> Path | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    getter = getattr(imageio_ffmpeg, "get_ffmpeg_exe", None)
    if not callable(getter):
        return None
    try:
        exe = Path(getter())
    except Exception:  # noqa: BLE001
        return None
    return exe if exe.is_file() else None


def _from_site_packages() -> Path | None:
    """Find a leftover/bundled binary under site-packages/imageio_ffmpeg/binaries."""
    names = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg",)
    candidates: list[Path] = []
    for root in sys.path:
        if not root:
            continue
        bin_dir = Path(root) / "imageio_ffmpeg" / "binaries"
        if not bin_dir.is_dir():
            continue
        for name in names:
            p = bin_dir / name
            if p.is_file():
                candidates.append(p)
        # Versioned imageio-ffmpeg builds (e.g. ffmpeg-win-x86_64-v7.1.exe)
        candidates.extend(sorted(bin_dir.glob("ffmpeg*.exe" if os.name == "nt" else "ffmpeg*")))
    for p in candidates:
        if p.is_file() and p.name.lower().startswith("ffmpeg"):
            return p
    return None


@lru_cache(maxsize=1)
def resolve_ffmpeg() -> str:
    """Return path to ffmpeg, preferring PATH then imageio-ffmpeg binaries."""
    found = shutil.which("ffmpeg")
    if found:
        return found

    exe = _from_imageio_api() or _from_site_packages()
    if exe is None:
        raise RuntimeError(
            "ffmpeg not found on PATH and no imageio-ffmpeg binary is available "
            "(pip install imageio-ffmpeg)"
        )

    bin_dir = exe.parent
    # Expose a stable ffmpeg(.exe) name for shutil.which / child processes.
    target = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not target.exists():
        shutil.copy2(exe, target)
        exe = target
    elif target != exe and target.is_file():
        exe = target

    _ensure_on_path(bin_dir)
    found = shutil.which("ffmpeg")
    return found or str(exe)
