"""Run live proposal-assistance benchmarks on real-world external families."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.real_world_proposal_assist import run_real_world_proposal_assist_benchmark


def main() -> None:
    families = sys.argv[1:] or None
    summary = run_real_world_proposal_assist_benchmark(families=families)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
