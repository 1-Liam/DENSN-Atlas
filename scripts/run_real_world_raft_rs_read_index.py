"""Run the real-world raft-rs current-term read-index evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.raft_rs_read_index_current_term import run_real_world_raft_rs_benchmark


def main() -> None:
    summary = run_real_world_raft_rs_benchmark()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
