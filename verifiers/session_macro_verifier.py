"""External verifier for Pathway A session-macro compression tasks."""

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
    start_token: str,
    update_token: str,
    finish_token: str,
    module_count: int,
) -> bool:
    expected: list[str] = []
    for index in range(1, module_count + 1):
        expected.extend(
            [
                f"{start_token}_{index}",
                f"{update_token}_{index}",
                f"{finish_token}_{index}",
            ]
        )
    return trace == expected


def verify_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(str(payload["manifest_path"])).resolve()
    manifest = load_json(manifest_path)
    source_path = (manifest_path.parent / str(manifest["source_code_path"])).resolve()
    source_text = source_path.read_text(encoding="utf-8")

    roles = manifest.get("roles", {})
    module_count = int(manifest.get("module_count", 1))
    start_token = str(roles.get("start", "START"))
    update_token = str(roles.get("update", "UPDATE"))
    finish_token = str(roles.get("finish", "FINISH"))
    combined_roles = Counter(
        str(role)
        for role in [
            *payload.get("canonical_parent_roles", payload.get("parent_roles", [])),
            *payload.get("canonical_blanket_roles", payload.get("blanket_roles", [])),
        ]
    )

    if combined_roles["open"] < 1 or combined_roles["write"] < 1 or combined_roles["close"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_macro_roles",
                "combined_roles": dict(combined_roles),
            },
            "artifact_ids": [],
            "verifier_name": "session_macro_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if "def validate_trace" not in source_text:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {"reason": "source_missing_validator"},
            "artifact_ids": [],
            "verifier_name": "session_macro_verifier",
            "details": {"source_path": str(source_path)},
        }

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            list(trace),
            start_token=start_token,
            update_token=update_token,
            finish_token=finish_token,
            module_count=module_count,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "session_macro_verifier",
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
            start_token=start_token,
            update_token=update_token,
            finish_token=finish_token,
            module_count=module_count,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {
                    "reason": "invalid_trace_accepted",
                    "trace": trace,
                },
                "artifact_ids": [],
                "verifier_name": "session_macro_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "session_macro_verifier",
        "details": {
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "valid_trace_count": valid_trace_count,
            "invalid_trace_count": invalid_trace_count,
            "source_contains_explicit_session_macro": "session_macro_state" in source_text,
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
