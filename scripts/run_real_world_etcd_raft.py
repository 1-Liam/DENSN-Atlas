"""Run the real-world etcd/raft current-term evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.etcd_raft_current_term import run_real_world_etcd_raft_benchmark


def main() -> None:
    summary = run_real_world_etcd_raft_benchmark()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
