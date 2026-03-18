"""Write the raw-first master summary for the external real-world lane."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.real_world_master_summary import run_real_world_master_summary


def main() -> None:
    summary = run_real_world_master_summary()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
