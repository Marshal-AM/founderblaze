#!/usr/bin/env python3
"""Tiny Google Veo smoke via genblaze-google.

Generates the shortest supported clip (4s, 720p) with Veo 3.1 preview.
Mirrors reference/genblaze/examples/veo_video_pipeline.py.

Usage (from repo root):
    uv run python scripts/veo_tiny_smoke.py
    uv run python scripts/veo_tiny_smoke.py --prompt "A red ball rolling on a white table"
    uv run python scripts/veo_tiny_smoke.py --out-dir ./tmp/veo-smoke

Requires GEMINI_API_KEY in the environment or repo-root .env.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load repo-root .env without requiring python-dotenv."""
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tiny Veo smoke (Genblaze Google)")
    parser.add_argument(
        "--prompt",
        default="A single red ball rolls slowly across a plain white table under soft daylight.",
        help="Text prompt for Veo",
    )
    parser.add_argument(
        "--model",
        default="veo-3.1-generate-preview",
        help="Veo model id (default: veo-3.1-generate-preview; older 2.0/3.0 slugs may be DEAD)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=4,
        choices=(4, 6, 8),
        help="Clip length in seconds (Veo allows 4/6/8)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tmp/veo-smoke"),
        help="Directory to copy the finished MP4 into",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Pipeline timeout seconds",
    )
    args = parser.parse_args(argv)

    _load_dotenv()
    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        print("Missing GEMINI_API_KEY (set env or repo-root .env)", file=sys.stderr)
        return 1

    from genblaze_core import Modality, Pipeline
    from genblaze_google import VeoProvider

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Veo smoke: model={args.model} duration={args.duration}s "
        f"resolution=720p → {out_dir}",
        flush=True,
    )

    provider = VeoProvider(output_dir=out_dir)
    result = (
        Pipeline("veo-tiny-smoke", project_id="founderblaze-smoke")
        .step(
            provider,
            model=args.model,
            prompt=args.prompt,
            modality=Modality.VIDEO,
            aspect_ratio="16:9",
            duration_seconds=args.duration,
            resolution="720p",
            # Do not pass enhance_prompt: veo-3.1 rejects the field entirely.
        )
        .run(timeout=args.timeout, max_retries=1, raise_on_failure=True)
    )

    # Pipeline.run returns a PipelineResult in current genblaze; tolerate tuple too.
    run = getattr(result, "run", None)
    if run is None and isinstance(result, tuple):
        run = result[0]
    if run is None:
        run = result

    step = run.steps[0]
    print(f"status={step.status} run_id={run.run_id}", flush=True)
    if not step.assets:
        print("No video asset returned", file=sys.stderr)
        return 1

    asset = step.assets[0]
    url = getattr(asset.url, "url", None) or str(asset.url)
    print(f"asset_url={url}", flush=True)

    # Prefer a stable local filename under out_dir.
    dest = out_dir / "tiny-veo.mp4"
    if url.startswith("file:"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)
        src = Path(unquote(parsed.path))
        if src.as_posix().startswith("/") and len(src.as_posix()) > 2 and src.as_posix()[2] == ":":
            # Windows file:///C:/... → /C:/... → C:/...
            src = Path(src.as_posix()[1:])
        if src.is_file() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        elif src.is_file():
            dest = src
    elif Path(url).is_file():
        shutil.copy2(url, dest)
    elif url.startswith("http://") or url.startswith("https://"):
        # Gemini Developer API returns a Files download URL; pull bytes locally.
        import urllib.request

        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        req = urllib.request.Request(
            url,
            headers={"x-goog-api-key": api_key} if api_key else {},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())

    if dest.is_file():
        print(f"saved={dest} bytes={dest.stat().st_size}", flush=True)
    else:
        print("Video generated but could not copy to out-dir; see asset_url above.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
