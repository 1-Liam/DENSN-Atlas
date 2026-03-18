"""External verifier for the real-world redislock refresh bundle."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_REPO = "https://github.com/bsm/redislock"
EXPECTED_COMMIT = "6ba61a38e6e67c455ea775ad521ebbd0868cf97b"


def normalize_whitespace(text: str) -> str:
    return " ".join(str(text).split())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def trace_is_valid(
    trace: list[str],
    *,
    open_token: str,
    close_token: str,
    action_token: str,
) -> bool:
    active = False
    action_count = 0
    for token in trace:
        if token == open_token:
            if active:
                return False
            active = True
            action_count = 0
        elif token == action_token:
            if not active:
                return False
            action_count += 1
        elif token == close_token:
            if not active or action_count < 1:
                return False
            active = False
        else:
            return False
    return not active


def verify_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(str(payload["manifest_path"])).resolve()
    manifest = load_json(manifest_path)
    source_path = (manifest_path.parent / str(manifest["source_code_path"])).resolve()
    source_text = source_path.read_text(encoding="utf-8")
    normalized_source_text = normalize_whitespace(source_text)

    provenance = dict(manifest.get("provenance", {}))
    if (
        provenance.get("repo") != EXPECTED_REPO
        or provenance.get("upstream_commit") != EXPECTED_COMMIT
    ):
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "invalid_upstream_provenance",
                "repo": provenance.get("repo"),
                "upstream_commit": provenance.get("upstream_commit"),
            },
            "artifact_ids": [],
            "verifier_name": "redislock_refresh_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }

    parent_roles = Counter(
        str(role) for role in payload.get("canonical_parent_roles", payload.get("parent_roles", []))
    )
    blanket_roles = Counter(
        str(role)
        for role in payload.get("canonical_blanket_roles", payload.get("blanket_roles", []))
    )
    if parent_roles["open"] < 1 or parent_roles["close"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_parent_roles",
                "parent_roles": dict(parent_roles),
            },
            "artifact_ids": [],
            "verifier_name": "redislock_refresh_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if blanket_roles["write"] < int(manifest.get("write_count", 1)):
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_required_blanket_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "redislock_refresh_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }

    markers = {
        "Obtain(": "Obtain(" in source_text,
        "Refresh(": "Refresh(" in source_text,
        "Release(": "Release(" in source_text,
        "ErrNotObtained": "ErrNotObtained" in source_text,
        "ErrLockNotHeld": "ErrLockNotHeld" in source_text,
        "TestLock_Refresh": "TestLock_Refresh" in source_text,
        "TestLock_Refresh_expired": "TestLock_Refresh_expired" in source_text,
        "TestLock_Release_expired": "TestLock_Release_expired" in source_text,
        "Yay, I still have my lock!": "Yay, I still have my lock!" in normalized_source_text,
    }
    if not all(markers.values()):
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_expected_source_markers",
                "markers": markers,
            },
            "artifact_ids": [],
            "verifier_name": "redislock_refresh_verifier",
            "details": {"source_path": str(source_path)},
        }

    roles = manifest.get("roles", {})
    open_token = str(roles.get("obtain", "OBTAIN"))
    close_token = str(roles.get("release", "RELEASE"))
    action_token = str(roles.get("refresh", "REFRESH"))

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            list(trace),
            open_token=open_token,
            close_token=close_token,
            action_token=action_token,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "redislock_refresh_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    invalid_items = [
        *manifest.get("failing_tests", []),
        *manifest.get("counterexamples", []),
        *manifest.get("logs", []),
    ]
    for item in invalid_items:
        invalid_trace_count += 1
        trace = list(item.get("trace", []))
        if trace and trace_is_valid(
            trace,
            open_token=open_token,
            close_token=close_token,
            action_token=action_token,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {
                    "reason": "invalid_trace_accepted",
                    "trace": trace,
                    "name": item.get("name"),
                },
                "artifact_ids": [],
                "verifier_name": "redislock_refresh_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "redislock_refresh_verifier",
        "details": {
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "valid_trace_count": valid_trace_count,
            "invalid_trace_count": invalid_trace_count,
            "upstream_commit": provenance.get("upstream_commit"),
            "markers": markers,
        },
    }


def main() -> None:
    claim_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    claim = load_json(claim_path)
    result = verify_manifest(dict(claim.get("payload", {})))
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
