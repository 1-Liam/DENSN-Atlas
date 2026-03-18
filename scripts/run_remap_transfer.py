"""Run the cross-family remap transfer benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.remap_transfer import run_remap_transfer_benchmark


def main() -> None:
    summary = run_remap_transfer_benchmark(output_dir="artifacts/phase6")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
