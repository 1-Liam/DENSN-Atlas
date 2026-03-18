"""Run the artifact-backed formal protocol benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.benchmarks.formal_protocol import run_formal_protocol_benchmark


def main() -> None:
    summary = run_formal_protocol_benchmark()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
