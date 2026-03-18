"""Run the public-release quality gate for the frozen DENSN repo."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact

OUTPUT_PATH = ROOT / "artifacts" / "readiness" / "release_audit.json"

COMMANDS: list[dict[str, Any]] = [
    {
        "name": "ruff_check",
        "command": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "densn",
            "scripts",
            "verifiers",
            "tests",
        ],
    },
    {
        "name": "pytest",
        "command": [sys.executable, "-m", "pytest", "-q"],
    },
    {
        "name": "core_integrity_audit",
        "command": [sys.executable, "scripts/run_core_integrity_audit.py"],
    },
    {
        "name": "package_repro_kit",
        "command": [sys.executable, "scripts/package_repro_kit.py"],
    },
    {
        "name": "verify_repro_run",
        "command": [sys.executable, "scripts/verify_repro_run.py"],
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_command(command: list[str]) -> list[str]:
    display = list(command)
    if display and Path(display[0]).name.lower().startswith("python"):
        display[0] = "python"
    return display


def _run_command(stage: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        stage["command"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    elapsed = round(time.perf_counter() - started, 3)
    return {
        "name": stage["name"],
        "command": _display_command(stage["command"]),
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "elapsed_seconds": elapsed,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def main() -> None:
    version = artifact_version_info("readiness", root=ROOT)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = [_run_command(stage) for stage in COMMANDS]
    core_integrity = _read_json(ROOT / "artifacts" / "readiness" / "core_integrity_audit.json")
    repro_verification = _read_json(
        ROOT / "artifacts" / "phase12" / "repro_verification_summary.json"
    )

    summary = {
        "artifact_version": version,
        "commands": results,
        "checks": {
            "all_commands_passed": all(result["ok"] for result in results),
            "core_integrity_proceed_recommended": bool(
                core_integrity.get("readiness", {}).get("proceed_recommended")
            ),
            "repro_verification_passed": bool(repro_verification.get("verification_passed")),
        },
    }
    summary["release_ready"] = all(summary["checks"].values())

    write_json_artifact(OUTPUT_PATH, summary, version=version)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
