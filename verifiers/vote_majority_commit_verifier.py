"""External verifier for role-remapped vote-majority transfer tasks."""

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
    propose_token: str,
    decide_token: str,
    barrier_token: str,
    required_vote_count: int,
) -> bool:
    active = False
    barrier = False
    vote_count = 0
    for token in trace:
        if token == propose_token:
            active = True
            barrier = False
            vote_count = 0
        elif token == barrier_token:
            if not active:
                return False
            barrier = True
        elif token.startswith("VOTE_"):
            if not active or not barrier:
                return False
            vote_count += 1
        elif token == decide_token:
            if not active or not barrier or vote_count < required_vote_count:
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

    roles = manifest.get("roles", {})
    propose_token = str(roles.get("propose", "PROPOSE"))
    decide_token = str(roles.get("decide", "DECIDE"))
    barrier_token = str(roles.get("barrier", "BARRIER"))
    required_vote_count = int(manifest.get("required_vote_count", 2))

    parent_roles = Counter(
        str(role) for role in payload.get("canonical_parent_roles", payload.get("parent_roles", []))
    )
    blanket_roles = Counter(
        str(role)
        for role in payload.get("canonical_blanket_roles", payload.get("blanket_roles", []))
    )

    if parent_roles["commit"] < 1 or parent_roles["pending"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_parent_roles",
                "parent_roles": dict(parent_roles),
            },
            "artifact_ids": [],
            "verifier_name": "vote_majority_commit_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if blanket_roles["ack"] < required_vote_count or blanket_roles["clear"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_blanket_roles",
                "blanket_roles": dict(blanket_roles),
                "required_vote_count": required_vote_count,
            },
            "artifact_ids": [],
            "verifier_name": "vote_majority_commit_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if "prepare" not in blanket_roles:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_prepare_blanket_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "vote_majority_commit_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if "def validate_trace" not in source_text:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {"reason": "source_missing_validator"},
            "artifact_ids": [],
            "verifier_name": "vote_majority_commit_verifier",
            "details": {"source_path": str(source_path)},
        }

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            list(trace),
            propose_token=propose_token,
            decide_token=decide_token,
            barrier_token=barrier_token,
            required_vote_count=required_vote_count,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "vote_majority_commit_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    for test in manifest.get("failing_tests", []):
        invalid_trace_count += 1
        trace = list(test.get("trace", []))
        if trace_is_valid(
            trace,
            propose_token=propose_token,
            decide_token=decide_token,
            barrier_token=barrier_token,
            required_vote_count=required_vote_count,
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
                "verifier_name": "vote_majority_commit_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    for counterexample in manifest.get("counterexamples", []):
        invalid_trace_count += 1
        trace = list(counterexample.get("trace", []))
        if trace_is_valid(
            trace,
            propose_token=propose_token,
            decide_token=decide_token,
            barrier_token=barrier_token,
            required_vote_count=required_vote_count,
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
                "verifier_name": "vote_majority_commit_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "vote_majority_commit_verifier",
        "details": {
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "valid_trace_count": valid_trace_count,
            "invalid_trace_count": invalid_trace_count,
            "source_contains_explicit_majority_ready": "majority_ready" in source_text,
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
