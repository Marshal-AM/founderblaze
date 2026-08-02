from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.competitor_research.pipeline import run_competitor_research_pipeline
from founderblaze.core.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="FounderBlaze competitor-research live CLI (PDF uploaded to B2 only)"
    )
    parser.add_argument("--product-name", required=True, help="Product / company name")
    parser.add_argument(
        "--product-url",
        default=None,
        help="Optional product homepage URL",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_competitor_research_pipeline(
        job_id=job_id,
        product_name=args.product_name,
        product_url=args.product_url,
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
