from __future__ import annotations

import argparse
import json
import sys
import uuid

from founderblaze.core.logging import setup_logging
from founderblaze.outreach.pipeline import run_outreach_pipeline


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="FounderBlaze outreach live CLI")
    parser.add_argument("--website-url", required=True, help="Company website URL")
    parser.add_argument("--sheet-url", default=None, help="Public spreadsheet URL")
    parser.add_argument(
        "--sheet-path",
        default=None,
        help="Local spreadsheet path (CLI/smoke)",
    )
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument(
        "--no-b2",
        action="store_true",
        help="Skip Backblaze upload; keep local file:// PDF",
    )
    args = parser.parse_args(argv)
    if not args.sheet_url and not args.sheet_path:
        parser.error("Provide --sheet-url or --sheet-path")

    job_id = args.job_id or str(uuid.uuid4())
    result = run_outreach_pipeline(
        job_id=job_id,
        website_url=args.website_url,
        sheet_url=args.sheet_url,
        sheet_path=args.sheet_path,
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
