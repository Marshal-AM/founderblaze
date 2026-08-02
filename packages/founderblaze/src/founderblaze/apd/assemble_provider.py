from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from genblaze_core import Asset, Modality, ProviderCapabilities, StepType, SyncProvider

log = logging.getLogger("founderblaze.apd.assemble")


class AssembleProvider(SyncProvider):
    """Per-step LMNT narration + timed mux so A/V stay in sync.

    For each browser step: TTS that step's line, build a video clip from the
    frames captured during that step, pad/hold the clip to the audio length,
    then concatenate. This replaces one global voiceover over wall-clock video
    (which races ahead, then sits idle after speech ends).
    """

    name = "apd-assemble"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice: str = "lily",
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("LMNT_API_KEY", "")
        self.voice = voice

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        if not inputs:
            raise RuntimeError("AssembleProvider needs the record video Asset")

        record = inputs[0]
        meta = dict(getattr(record, "metadata", None) or {})
        work_dir = Path(meta.get("work_dir") or "")
        frames_dir = work_dir / "frames"
        meta_path = work_dir / "frames_meta.json"
        step_log_path = Path(meta.get("step_log") or (work_dir / "step_log.json"))
        plan = meta.get("plan") or {}

        if not frames_dir.is_dir():
            raise RuntimeError(f"frames dir missing: {frames_dir}")
        if not meta_path.is_file():
            raise RuntimeError(f"frames_meta.json missing: {meta_path}")
        if not step_log_path.is_file():
            raise RuntimeError(f"step_log missing: {step_log_path}")

        frames_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        step_log = json.loads(step_log_path.read_text(encoding="utf-8"))
        plan_steps = list(plan.get("steps") or [])
        if not step_log:
            raise RuntimeError("empty step_log")

        narration_by_id = {
            int(s["id"]): str(s.get("narration_draft") or "").strip()
            for s in plan_steps
            if s.get("id") is not None
        }

        from founderblaze.apd.ffmpeg_util import resolve_ffmpeg

        ffmpeg = resolve_ffmpeg()
        if not self.api_key:
            raise RuntimeError("LMNT_API_KEY is required for per-step narration")

        from lmnt import Lmnt

        client = Lmnt(api_key=self.api_key)
        seg_dir = work_dir / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        segment_paths: list[Path] = []

        for i, slog in enumerate(step_log):
            sid = int(slog["id"])
            start_ms = int(slog["start"])
            end_ms = int(slog["end"])
            # Include a little lead-in so the click/type isn't clipped
            if i > 0:
                prev_end = int(step_log[i - 1]["end"])
                start_ms = min(start_ms, max(prev_end, start_ms - 250))
            text = narration_by_id.get(sid) or str(slog.get("instruction") or "")[:120]
            if not text:
                text = f"Step {sid}."

            log.info(
                "assemble step %s/%s narrate chars=%s",
                i + 1,
                len(step_log),
                len(text),
            )
            audio_path = seg_dir / f"narration_{sid:02d}.mp3"
            _lmnt_tts(client, text=text, voice=self.voice, out_path=audio_path)
            audio_dur = _probe_duration(ffmpeg, audio_path)

            step_frames = [
                f
                for f in frames_meta
                if start_ms <= int(f["ts"]) <= end_ms
            ]
            if not step_frames:
                # nearest frame before/at start
                before = [f for f in frames_meta if int(f["ts"]) <= start_ms]
                step_frames = [before[-1]] if before else [frames_meta[0]]

            silent = seg_dir / f"video_{sid:02d}_silent.mp4"
            _frames_clip(step_frames, frames_dir, silent, target_duration=audio_dur)

            muxed = seg_dir / f"seg_{sid:02d}.mp4"
            _mux_pad_video_to_audio(ffmpeg, silent, audio_path, muxed, audio_dur)
            segment_paths.append(muxed)
            log.info(
                "assemble step %s done audio=%.2fs frames=%s",
                sid,
                audio_dur,
                len(step_frames),
            )

        log.info("assemble concat starting segments=%s", len(segment_paths))
        # Write into work_dir (not anonymous mkstemp) so a dead process still
        # leaves a diagnosable final.mp4 beside seg_XX.mp4.
        out = work_dir / "final.mp4"
        _concat_segments(ffmpeg, segment_paths, out)
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        log.info("assemble concat done path=%s bytes=%s", out, out.stat().st_size)
        step.assets.append(
            Asset(
                url=out.resolve().as_uri(),
                media_type="video/mp4",
                sha256=digest,
                metadata={"segments": len(segment_paths)},
            )
        )
        step.step_type = StepType.MIX
        return step


def _lmnt_tts(client: Any, *, text: str, voice: str, out_path: Path) -> None:
    text = text[:5000]
    log.info("lmnt generate start chars=%s voice=%s", len(text), voice)
    result = client.speech.generate(
        voice=voice,
        text=text,
        format="mp3",
        timeout=60.0,
    )
    data = result.read() if hasattr(result, "read") else bytes(result)
    out_path.write_bytes(data)
    log.info("lmnt generate done bytes=%s", len(data))


def _probe_duration(ffmpeg: str, path: Path) -> float:
    """Duration via ffmpeg stderr (works without a separate ffprobe binary)."""
    import re

    proc = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
    )
    blob = (proc.stderr or "") + (proc.stdout or "")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", blob)
    if not m:
        return 2.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return max(0.4, h * 3600 + mi * 60 + s)


def _frames_clip(
    frames: list[dict[str, Any]],
    frames_dir: Path,
    out_mp4: Path,
    *,
    target_duration: float,
) -> None:
    """Build a silent clip lasting exactly target_duration from step frames."""
    paths = [frames_dir / f["file"] for f in frames]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise RuntimeError("no frame files for clip")

    n = len(paths)
    # Distribute target duration evenly across frames (hold last)
    per = target_duration / max(n, 1)
    per = max(0.04, per)

    list_file = out_mp4.with_suffix(".txt")
    lines: list[str] = []
    for p in paths:
        escaped = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
        lines.append(f"duration {per:.6f}")
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
        "-t",
        f"{target_duration:.3f}",
        str(out_mp4),
    ]
    _run_ffmpeg(cmd, label="frame clip", timeout=120)


def _mux_pad_video_to_audio(
    ffmpeg: str,
    video: Path,
    audio: Path,
    out: Path,
    audio_dur: float,
) -> None:
    # Hold last video frame if clip is shorter than audio; cut if longer.
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-filter_complex",
        (
            f"[0:v]tpad=stop_mode=clone:stop_duration={audio_dur + 1:.3f}[v];"
            f"[v]trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS[vout]"
        ),
        "-map",
        "[vout]",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    _run_ffmpeg(cmd, label="segment mux", timeout=120)


def _concat_segments(
    ffmpeg: str,
    segments: list[Path],
    out: Path,
    *,
    timeout: int = 180,
) -> None:
    list_file = out.with_suffix(".concat.txt")
    lines = []
    for p in segments:
        escaped = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Re-encode directly — `-c copy` can hang on Windows when segment
    # timebases/codecs from per-step mux don't align cleanly.
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out),
    ]
    _run_ffmpeg(cmd, label="concat", timeout=timeout)


def _run_ffmpeg(cmd: list[str], *, label: str, timeout: int) -> None:
    log.info("%s: %s", label, " ".join(cmd[:8]) + " ...")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed: {(proc.stderr or '')[-600:]}")


def _local_path(url: str) -> Path | None:
    if not url:
        return None
    if url.startswith("file:"):
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)
    p = Path(url)
    return p if p.exists() else None
