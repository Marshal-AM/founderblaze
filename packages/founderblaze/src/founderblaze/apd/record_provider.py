from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Asset, Modality, ProviderCapabilities, SyncProvider

log = logging.getLogger("founderblaze.apd.record")


class RecordProvider(SyncProvider):
    """Firecrawl + Playwright CDP screencast as a Genblaze SyncProvider."""

    name = "apd-record"

    def __init__(
        self,
        *,
        website_url: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.website_url = website_url
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is required")

        plan = _load_plan(step)
        steps = plan.get("steps") or []
        if not steps:
            raise ValueError("Plan has no steps")

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="apd-record-"))
        frames_dir = work / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        from founderblaze.apd.browser import BrowserExecutor

        executor = BrowserExecutor(self.api_key)
        frames: list[dict[str, Any]] = []
        step_log_path = work / "step_log.json"
        try:
            executor.scrape(self.website_url)
            cdp_url = executor.warmup()
            executor.start_recording(cdp_url)
            step_results = executor.run_steps(steps)
            if not step_results:
                raise RuntimeError("No browser steps were executed")
            frames = executor.stop_recording()
            executor.save_frames(str(frames_dir))
            executor.save_step_log(str(step_log_path))
            frames_meta_path = work / "frames_meta.json"
            frames_meta_path.write_text(
                json.dumps(
                    [
                        {
                            "i": i,
                            "ts": int(f.get("ts") or 0),
                            "file": f"frame_{i:06d}.jpg",
                        }
                        for i, f in enumerate(frames)
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            try:
                executor.close_session("record provider finished")
            except Exception as exc:  # noqa: BLE001
                log.warning("close_session: %s", exc)

        if not frames:
            raise RuntimeError("No screencast frames captured")

        # Preview silent encode (optional); assemble rebuilds per-step clips.
        silent_mp4 = work / "screencast_silent.mp4"
        log.info("encoding silent screencast frames=%s", len(frames))
        wall_s = _frames_to_mp4(frames, frames_dir, silent_mp4)
        log.info("silent screencast ready duration_s=%.1f path=%s", wall_s, silent_mp4)
        digest = hashlib.sha256(silent_mp4.read_bytes()).hexdigest()
        uri = silent_mp4.resolve().as_uri()
        step.assets.append(
            Asset(
                url=uri,
                media_type="video/mp4",
                sha256=digest,
                metadata={
                    "work_dir": str(work),
                    "step_log": str(step_log_path),
                    "frames_meta": str(work / "frames_meta.json"),
                    "step_results": step_results,
                    "plan": plan,
                    "frame_count": len(frames),
                    "duration_seconds": wall_s,
                },
            )
        )
        return step


def _frames_to_mp4(
    frames: list[dict[str, Any]],
    frames_dir: Path,
    out_mp4: Path,
) -> float:
    """Build MP4 using wall-clock gaps between CDP frame timestamps.

    Fixed-fps packing (e.g. 8fps × N frames) compresses a multi-minute
    recording into seconds when screencast emits sparsely during interact.
    """
    if not frames:
        raise RuntimeError("No frames to encode")

    # Ensure JPEGs exist and align with frames list order
    paths: list[Path] = []
    for i, frame in enumerate(frames):
        p = frames_dir / f"frame_{i:06d}.jpg"
        if not p.exists():
            p.write_bytes(frame["data"])
        paths.append(p)

    timestamps = [int(f.get("ts") or 0) for f in frames]
    # If timestamps missing/invalid, fall back to ~2fps (CDP often lands near that)
    use_ts = (
        len(timestamps) >= 2
        and timestamps[0] > 0
        and timestamps[-1] > timestamps[0]
    )

    list_file = out_mp4.with_suffix(".frames.txt")
    lines: list[str] = []
    durations: list[float] = []
    for i, p in enumerate(paths):
        if use_ts and i < len(paths) - 1:
            gap_ms = timestamps[i + 1] - timestamps[i]
            # Keep real pacing; only clamp pathological gaps
            duration = max(0.04, min(gap_ms / 1000.0, 5.0))
        elif use_ts and i == len(paths) - 1:
            duration = 0.5  # hold last frame briefly; may extend below
        else:
            duration = 0.5  # 2fps fallback — closer to live interact pacing
        durations.append(duration)

    if use_ts:
        span = (timestamps[-1] - timestamps[0]) / 1000.0 + 0.5
        summed = sum(durations)
        if span > summed:
            durations[-1] += span - summed

    total = sum(durations)
    for p, duration in zip(paths, durations, strict=True):
        escaped = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
        lines.append(f"duration {duration:.6f}")
    last = str(paths[-1].resolve()).replace("\\", "/").replace("'", r"'\''")
    lines.append(f"file '{last}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    from founderblaze.apd.ffmpeg_util import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(out_mp4),
    ]
    log.info(
        "ffmpeg frames->mp4 frames=%s duration_s=%.1f timed=%s",
        len(paths),
        total,
        use_ts,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg frames->mp4 failed: {proc.stderr[-800:]}")
    return total


def _load_plan(step) -> dict[str, Any]:  # noqa: ANN001
    """Prefer plan Asset from input_from; fall back to step.prompt JSON."""
    for asset in list(getattr(step, "inputs", None) or []):
        meta = dict(getattr(asset, "metadata", None) or {})
        if isinstance(meta.get("json"), dict) and meta["json"].get("steps"):
            return dict(meta["json"])
        text = meta.get("text")
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text)
                if parsed.get("steps"):
                    return parsed
            except json.JSONDecodeError:
                pass
        url = str(getattr(getattr(asset, "url", None), "url", None) or asset.url or "")
        if url.startswith("file:"):
            from urllib.parse import unquote, urlparse

            parsed_url = urlparse(url)
            path = unquote(parsed_url.path)
            if path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]
            p = Path(path)
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))

    plan_text = step.prompt or "{}"
    try:
        return json.loads(plan_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "RecordProvider expects plan JSON via input_from or prompt"
        ) from exc
