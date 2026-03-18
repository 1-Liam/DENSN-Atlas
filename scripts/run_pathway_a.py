"""Run the Pathway A benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.pathway_a import run_pathway_a_benchmark


def main() -> None:
    summary = run_pathway_a_benchmark(output_dir="artifacts/phase8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
