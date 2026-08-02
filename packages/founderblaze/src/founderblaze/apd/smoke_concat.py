"""Smoke: after per-step ``seg_XX.mp4`` exist, concat must finish and the
pipeline must transition past assemble.

Why APD looked hung here
------------------------
Failed runs left ``narration_*.mp3`` + ``seg_*.mp4`` in the work dir but no
``final.mp4``. That looked like a forever-hang on the last ffmpeg concat.

Reproduction on the exact failed segments showed **neither** ``-c copy`` nor
re-encode hangs (both finish in ~1–3s). Open ``mkstemp`` fds also do **not**
block ffmpeg writes on this Windows host.

What actually misled us:

1. Final output used to be an anonymous ``tempfile.mkstemp`` path **outside**
   the work dir — so a successful concat still looked like "final missing".
2. PowerShell ``> file.log`` buffering hid later ``assemble concat`` lines,
   so the terminal appeared frozen while work continued (or after a kill).
3. Investigating agents killed leftover ``apd-live`` processes, leaving work
   dirs frozen mid/post-segment with no final artifact in-tree.

This smoke guards the real contract: segments → ``final.mp4`` → Genblaze
step completion (the transition into sink / CLI JSON).

Usage
-----
::

    uv run --package founderblaze-apd python -m founderblaze.apd.smoke_concat
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from genblaze_core import Asset, Modality, Pipeline, ProviderCapabilities, SyncProvider

from founderblaze.apd.assemble_provider import _concat_segments


def _require_ffmpeg() -> str:
    from founderblaze.apd.ffmpeg_util import resolve_ffmpeg

    try:
        return resolve_ffmpeg()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def _make_tiny_segment(ffmpeg: str, out: Path, *, color: str, seconds: float = 0.4) -> None:
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x240:d={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=stereo:d={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"make segment failed: {(proc.stderr or '')[-400:]}")


def test_segments_to_final_mp4() -> Path:
    """Contract: seg_XX → work_dir/final.mp4 completes quickly."""
    ffmpeg = _require_ffmpeg()
    work = Path(tempfile.mkdtemp(prefix="apd-concat-smoke-"))
    seg_dir = work / "segments"
    seg_dir.mkdir()
    segments: list[Path] = []
    for i, color in enumerate(("red", "green", "blue"), start=1):
        p = seg_dir / f"seg_{i:02d}.mp4"
        _make_tiny_segment(ffmpeg, p, color=color)
        segments.append(p)

    out = work / "final.mp4"
    started = time.perf_counter()
    _concat_segments(ffmpeg, segments, out, timeout=60)
    elapsed = time.perf_counter() - started
    if not out.is_file() or out.stat().st_size < 1000:
        raise AssertionError(f"final.mp4 missing or tiny: {out}")
    if elapsed > 60:
        raise AssertionError(f"concat too slow: {elapsed:.1f}s")
    print(f"OK  segments→final.mp4 in {elapsed:.2f}s ({out.stat().st_size} bytes)")
    return work


def test_real_failed_run_segments_if_present() -> None:
    """If a prior hung work dir still exists, concat those exact seg_XX files."""
    candidates = sorted(
        Path(tempfile.gettempdir()).glob("apd-*/segments"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for seg_dir in candidates:
        parent_name = seg_dir.parent.name
        # Skip this smoke's own temp dirs.
        if "concat-smoke" in parent_name or "concat-lock" in parent_name:
            continue
        segs = sorted(seg_dir.glob("seg_*.mp4"))
        # Real APD demos produce several steps; ignore tiny accidental leftovers.
        if len(segs) < 4:
            continue
        ffmpeg = _require_ffmpeg()
        out = seg_dir.parent / "final.mp4"
        started = time.perf_counter()
        _concat_segments(ffmpeg, segs, out, timeout=90)
        elapsed = time.perf_counter() - started
        if out.stat().st_size < 1000:
            raise AssertionError(f"real-run concat tiny: {out}")
        print(
            f"OK  real-run {parent_name}: {len(segs)} segs → "
            f"final.mp4 in {elapsed:.2f}s ({out.stat().st_size} bytes)"
        )
        return
    print("SKIP no prior apd-*/segments with seg_*.mp4 found")


class _FinalVideoProvider(SyncProvider):
    """Stand-in for AssembleProvider after concat — emits the final MP4 Asset."""

    name = "apd-smoke-final"

    def __init__(self, final_mp4: Path) -> None:
        super().__init__()
        self.final_mp4 = final_mp4

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=False,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        data = self.final_mp4.read_bytes()
        step.assets.append(
            Asset(
                url=self.final_mp4.resolve().as_uri(),
                media_type="video/mp4",
                sha256=hashlib.sha256(data).hexdigest(),
                metadata={"smoke": True, "bytes": len(data)},
            )
        )
        return step


def test_pipeline_transitions_past_final_video(work: Path) -> None:
    """Next step after assemble: Genblaze Pipeline must complete (sink=None)."""
    final = work / "final.mp4"
    if not final.is_file():
        raise AssertionError("need final.mp4 from prior smoke step")

    started = time.perf_counter()
    result = (
        Pipeline("apd-concat-smoke", tenant_id="smoke", project_id="apd")
        .step(
            _FinalVideoProvider(final),
            model="apd-smoke-final",
            modality=Modality.VIDEO,
        )
        .run(pipeline_timeout=60, raise_on_failure=True)
    )
    elapsed = time.perf_counter() - started
    status = getattr(result.run, "status", None)
    if str(status).lower() in {"failed", "error"}:
        raise AssertionError(f"pipeline failed status={status}")
    assets = []
    for s in getattr(result.run, "steps", []) or []:
        assets.extend(getattr(s, "assets", None) or [])
    if not assets:
        raise AssertionError("pipeline completed with zero assets")
    print(
        f"OK  pipeline transition past final video in {elapsed:.2f}s "
        f"status={status} assets={len(assets)} run_id={result.run.run_id}"
    )


def main() -> int:
    print("=== APD assemble concat → next-step smoke ===")
    print(f"platform={os.name} ffmpeg={_require_ffmpeg()}")
    work = test_segments_to_final_mp4()
    try:
        test_real_failed_run_segments_if_present()
        test_pipeline_transitions_past_final_video(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("=== ALL SMOKES PASSED ===")
    print()
    print("Full APD pipeline (stream logs; do not redirect with PowerShell `>`):")
    print(
        '  uv run --package founderblaze-apd founderblaze-apd-live '
        '--no-b2 '
        '--url "https://surveys.free/google-forms-alternative/" '
        '--script "Show homepage, create a Birthday RSVP form, add allergies yes/no, save."'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
