from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.apd.pipeline import run_apd_pipeline
from founderblaze.core.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    # Ensure imageio-ffmpeg lands on PATH before record/assemble spawn ffmpeg.
    from founderblaze.apd.ffmpeg_util import resolve_ffmpeg

    resolve_ffmpeg()
    parser = argparse.ArgumentParser(description="FounderBlaze APD live CLI")
    parser.add_argument("--url", required=True, help="Target website URL")
    parser.add_argument("--script", required=True, help="Demo script")
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// video artifact",
    )
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_apd_pipeline(
        job_id=job_id,
        website_url=args.url,
        script=args.script,
        upload_to_b2=not args.no_b2,
        on_step_complete=lambda e: print(
            f"step: {getattr(getattr(e, 'step', e), 'provider', e)}",
            file=sys.stderr,
            flush=True,
        ),
    )
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
