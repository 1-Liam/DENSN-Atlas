"""External verifier for artifact-backed credit-window tasks."""

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
    *,
    grant_token: str,
    revoke_token: str,
    charge_token: str,
    balance_token: str,
) -> bool:
    active = False
    balance_live = False
    for token in trace:
        if token == grant_token:
            if active:
                return False
            active = True
            balance_live = False
        elif token == balance_token:
            if not active:
                return False
            balance_live = True
        elif token == charge_token:
            if not active or not balance_live:
                return False
        elif token == revoke_token:
            if not active:
                return False
            active = False
            balance_live = False
        else:
            return False
    return not active


def verify_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(str(payload["manifest_path"])).resolve()
    manifest = load_json(manifest_path)
    source_path = (manifest_path.parent / str(manifest["source_code_path"])).resolve()
    source_text = source_path.read_text(encoding="utf-8")

    roles = manifest.get("roles", {})
    grant_token = str(roles.get("grant", "GRANT"))
    revoke_token = str(roles.get("revoke", "REVOKE"))
    charge_token = str(roles.get("charge", "CHARGE"))
    balance_token = str(roles.get("balance", "BALANCE"))
    parent_roles = Counter(str(role) for role in payload.get("parent_roles", []))
    blanket_roles = Counter(str(role) for role in payload.get("blanket_roles", []))

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
            "verifier_name": "credit_window_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if blanket_roles["write"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_charge_blanket_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "credit_window_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if blanket_roles["epoch"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_balance_blanket_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "credit_window_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if "def validate_trace" not in source_text:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {"reason": "source_missing_validator"},
            "artifact_ids": [],
            "verifier_name": "credit_window_verifier",
            "details": {"source_path": str(source_path)},
        }

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            list(trace),
            grant_token=grant_token,
            revoke_token=revoke_token,
            charge_token=charge_token,
            balance_token=balance_token,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "credit_window_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    for item in [
        *manifest.get("failing_tests", []),
        *manifest.get("counterexamples", []),
        *manifest.get("logs", []),
    ]:
        trace = list(item.get("trace", []))
        if not trace:
            continue
        invalid_trace_count += 1
        if trace_is_valid(
            trace,
            grant_token=grant_token,
            revoke_token=revoke_token,
            charge_token=charge_token,
            balance_token=balance_token,
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
                "verifier_name": "credit_window_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "credit_window_verifier",
        "details": {
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "valid_trace_count": valid_trace_count,
            "invalid_trace_count": invalid_trace_count,
            "source_contains_explicit_credit_live": "credit_live" in source_text,
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
