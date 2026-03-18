"""Run the phase-13 reviewer-policy precision campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.proposal_precision import run_proposal_precision_campaign


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the reviewer-policy precision campaign.")
    parser.add_argument(
        "--family",
        default="credit_window",
        help="Family to evaluate. Defaults to credit_window.",
    )
    parser.add_argument(
        "--fixed-pool-source",
        default=None,
        help="Optional path to a fixed pool artifact or prior proposal_precision summary.",
    )
    parser.add_argument(
        "--refresh-pool",
        action="store_true",
        help="Force a fresh live proposal pool instead of reusing the stable fixed pool artifact.",
    )
    args = parser.parse_args()

    summary = run_proposal_precision_campaign(
        output_dir="artifacts/phase13",
        family=args.family,
        fixed_pool_source_path=args.fixed_pool_source,
        refresh_pool=args.refresh_pool,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
