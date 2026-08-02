from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.app_kit.pipeline import run_app_kit_pipeline
from founderblaze.core.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="FounderBlaze app-kit live CLI")
    parser.add_argument("--product-name", required=True, help="Product / app name")
    parser.add_argument("--product-idea", required=True, help="Product idea / brief")
    parser.add_argument(
        "--brand-kit-url",
        default=None,
        help="Optional downloadable brand-kit ZIP URL",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// zip artifact",
    )
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_app_kit_pipeline(
        job_id=job_id,
        product_name=args.product_name,
        product_idea=args.product_idea,
        brand_kit_url=args.brand_kit_url,
        upload_to_b2=not args.no_b2,
        on_step_complete=lambda e: print(
            f"step: {getattr(getattr(e, 'step', e), 'provider', e)}",
            file=sys.stderr,
        ),
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
