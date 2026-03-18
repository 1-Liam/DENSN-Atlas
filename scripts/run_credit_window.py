"""Run the external credit-window benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.credit_window import run_credit_window_benchmark


def main() -> None:
    summary = run_credit_window_benchmark(output_dir="artifacts/phase12")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
