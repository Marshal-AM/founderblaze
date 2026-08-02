from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.core.logging import setup_logging
from founderblaze.pitch_deck.pipeline import run_pitch_deck_pipeline


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="FounderBlaze pitch-deck live CLI")
    parser.add_argument("--product-url", required=True, help="Product / landing page URL")
    parser.add_argument(
        "--funding-ask",
        required=True,
        help='Funding ask, e.g. "$500K seed" or "raise $2M Series A"',
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// PDF artifact",
    )
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_pitch_deck_pipeline(
        job_id=job_id,
        product_url=args.product_url,
        funding_ask=args.funding_ask,
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
