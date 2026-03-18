"""External verifier for role-remapped lease-lock transfer tasks."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def trace_is_valid(
    trace: list[str],
    acquire_token: str,
    release_token: str,
    mutate_token: str,
    *,
    epoch_token: str | None = None,
    required_epoch: bool = False,
) -> bool:
    active = False
    epoch_ready = False
    for token in trace:
        if token == acquire_token:
            if active:
                return False
            active = True
            epoch_ready = False
        elif epoch_token is not None and token == epoch_token:
            if not active:
                return False
            epoch_ready = True
        elif token == release_token:
            if not active:
                return False
            active = False
        elif token == mutate_token:
            if not active or (required_epoch and not epoch_ready):
                return False
        else:
            return False
    return not active


def verify_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(str(payload["manifest_path"])).resolve()
    manifest = load_json(manifest_path)
    source_path = (manifest_path.parent / str(manifest["source_code_path"])).resolve()
    source_text = source_path.read_text(encoding="utf-8")

    roles = manifest.get("roles", {})
    acquire_token = str(roles.get("acquire", "ACQUIRE"))
    release_token = str(roles.get("release", "RELEASE"))
    mutate_token = str(roles.get("mutate", "MUTATE"))
    epoch_token = roles.get("epoch")
    required_epoch = bool(manifest.get("required_epoch", False))
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
            "verifier_name": "lease_lock_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if blanket_roles["write"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_write_blanket",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "lease_lock_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if required_epoch and blanket_roles["epoch"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_epoch_blanket_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "lease_lock_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if "def validate_trace" not in source_text:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {"reason": "source_missing_validator"},
            "artifact_ids": [],
            "verifier_name": "lease_lock_verifier",
            "details": {"source_path": str(source_path)},
        }

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            trace,
            acquire_token,
            release_token,
            mutate_token,
            epoch_token=None if epoch_token is None else str(epoch_token),
            required_epoch=required_epoch,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "lease_lock_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    for test in manifest.get("failing_tests", []):
        invalid_trace_count += 1
        trace = list(test.get("trace", []))
        if trace_is_valid(
            trace,
            acquire_token,
            release_token,
            mutate_token,
            epoch_token=None if epoch_token is None else str(epoch_token),
            required_epoch=required_epoch,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {
                    "reason": "failing_test_accepted",
                    "trace": trace,
                    "name": test.get("name"),
                },
                "artifact_ids": [],
                "verifier_name": "lease_lock_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    for counterexample in manifest.get("counterexamples", []):
        invalid_trace_count += 1
        trace = list(counterexample.get("trace", []))
        if trace_is_valid(
            trace,
            acquire_token,
            release_token,
            mutate_token,
            epoch_token=None if epoch_token is None else str(epoch_token),
            required_epoch=required_epoch,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {
                    "reason": "counterexample_accepted",
                    "trace": trace,
                    "name": counterexample.get("name"),
                },
                "artifact_ids": [],
                "verifier_name": "lease_lock_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "lease_lock_verifier",
        "details": {
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "valid_trace_count": valid_trace_count,
            "invalid_trace_count": invalid_trace_count,
            "source_contains_explicit_lease_live": "lease_live" in source_text,
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
