"""Run the quorum proposal runtime benchmark under the shared DENSN loop."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.proposal_runtime import run_proposal_runtime_benchmark


def main() -> None:
    summary = run_proposal_runtime_benchmark(output_dir="artifacts/phase4", family="quorum_commit")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
