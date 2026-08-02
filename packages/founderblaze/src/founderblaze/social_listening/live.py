from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.core.logging import setup_logging
from founderblaze.social_listening.pipeline import run_social_listening_pipeline


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="FounderBlaze social-listening live CLI"
    )
    parser.add_argument("--product-url", required=True, help="Product website URL")
    parser.add_argument(
        "--product-name",
        default=None,
        help="Optional fallback name if scrape fails",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Cap recommendations (1–20)",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// PDF",
    )
    args = parser.parse_args(argv)
    if args.max_posts is not None and not (1 <= args.max_posts <= 20):
        parser.error("--max-posts must be between 1 and 20")

    job_id = args.job_id or str(uuid.uuid4())
    result = run_social_listening_pipeline(
        job_id=job_id,
        product_url=args.product_url,
        product_name=args.product_name,
        max_posts=args.max_posts,
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
