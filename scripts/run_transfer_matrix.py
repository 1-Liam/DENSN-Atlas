"""Run cross-family and negative-transfer checks for ontology reuse."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.transfer_matrix import run_transfer_matrix_benchmark


def main() -> None:
    summary = run_transfer_matrix_benchmark()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
