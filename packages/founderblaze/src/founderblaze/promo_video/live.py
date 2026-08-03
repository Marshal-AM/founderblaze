from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.core.logging import setup_logging
from founderblaze.promo_video.pipeline import run_promo_video_pipeline


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="FounderBlaze promo-video live CLI")
    parser.add_argument("--product-url", required=True, help="Product website URL")
    parser.add_argument(
        "--duration",
        type=int,
        default=8,
        choices=(4, 5, 6, 8, 10, 12, 15),
        help="Seedance clip length seconds (default 8)",
    )
    parser.add_argument(
        "--resolution",
        default="720p",
        choices=("480p", "720p", "1080p", "4k"),
        help="Video resolution (default 720p)",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// MP4",
    )
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_promo_video_pipeline(
        job_id=job_id,
        product_url=args.product_url,
        duration=args.duration,
        resolution=args.resolution,
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
