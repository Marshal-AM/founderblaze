from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.brand_kit.pipeline import run_brand_kit_pipeline
from founderblaze.core.logging import setup_logging


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="FounderBlaze brand-kit live CLI")
    parser.add_argument("--brand-name", required=True, help="Brand name")
    parser.add_argument("--description", required=True, help="Creative brief")
    parser.add_argument(
        "--pick",
        type=int,
        default=0,
        help="Logo concept index to use as primary mark (default 0)",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// zip artifact",
    )
    args = parser.parse_args(argv)

    job_id = args.job_id or str(uuid.uuid4())
    result = run_brand_kit_pipeline(
        job_id=job_id,
        brand_name=args.brand_name,
        description=args.description,
        pick=args.pick,
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
