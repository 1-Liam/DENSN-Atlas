"""Versioned artifact output helpers for reproducible research runs."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def compact_utc_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")


def git_sha(root: str | Path | None = None) -> str:
    repo_root = Path(root or Path(__file__).resolve().parents[1])
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
            timeout=5.0,
        )
    except Exception:
        return "nogit"
    sha = result.stdout.strip()
    return sha or "nogit"


def artifact_version_info(phase: str, root: str | Path | None = None) -> dict[str, str]:
    return {
        "phase": phase,
        "timestamp_utc": compact_utc_timestamp(),
        "git_sha": git_sha(root=root),
    }


def versioned_name(target: str | Path, version: dict[str, str]) -> str:
    path = Path(target)
    return (
        f"{path.stem}.{version['phase']}.{version['timestamp_utc']}."
        f"{version['git_sha']}{path.suffix}"
    )


def snapshot_artifact_file(
    target: str | Path,
    *,
    version: dict[str, str],
) -> dict[str, str]:
    stable_path = Path(target)
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    versioned_path = stable_path.with_name(versioned_name(stable_path, version))
    shutil.copy2(stable_path, versioned_path)
    return {
        **version,
        "stable_path": str(stable_path),
        "versioned_path": str(versioned_path),
    }


def write_json_artifact(
    target: str | Path,
    payload: Any,
    *,
    version: dict[str, str],
) -> dict[str, str]:
    stable_path = Path(target)
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    stable_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return snapshot_artifact_file(stable_path, version=version)


def write_text_artifact(
    target: str | Path,
    text: str,
    *,
    version: dict[str, str],
) -> dict[str, str]:
    stable_path = Path(target)
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    stable_path.write_text(text, encoding="utf-8")
    return snapshot_artifact_file(stable_path, version=version)
