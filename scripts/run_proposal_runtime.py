"""Run the in-loop proposal runtime benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.proposal_runtime import run_proposal_runtime_benchmark


def main() -> None:
    family = "protocol_guard"
    if len(sys.argv) > 1:
        family = sys.argv[1]
    summary = run_proposal_runtime_benchmark(family=family)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
