"""External verifier for the real-world etcd/raft current-term commit bundle."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_REPO = "https://github.com/etcd-io/raft"
EXPECTED_COMMIT = "bcec33429c39a8bade4c2472cc68cf6038a0664f"


def normalize_whitespace(text: str) -> str:
    return " ".join(str(text).split())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def trace_is_valid(
    trace: list[str],
    *,
    prepare_token: str,
    commit_token: str,
    clear_token: str,
    required_ack_count: int,
    stable_token: str | None,
    required_stable: bool,
    counter_prefix: str,
) -> bool:
    active = False
    clear = False
    stable = False
    ack_count = 0
    for token in trace:
        if token == prepare_token:
            active = True
            clear = False
            stable = False
            ack_count = 0
        elif token == clear_token:
            if not active:
                return False
            clear = True
        elif stable_token is not None and token == stable_token:
            if not active or not clear:
                return False
            stable = True
        elif token.startswith(counter_prefix):
            if not active or not clear:
                return False
            ack_count += 1
        elif token == commit_token:
            if (
                not active
                or not clear
                or ack_count < required_ack_count
                or (required_stable and not stable)
            ):
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
            "verifier_name": "etcd_raft_current_term_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }

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
            "verifier_name": "etcd_raft_current_term_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if (
        blanket_roles["ack"] < int(manifest.get("required_ack_count", 2))
        or blanket_roles["clear"] < 1
    ):
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_blanket_roles",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "etcd_raft_current_term_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }
    if bool(manifest.get("required_stable", False)) and blanket_roles["stable"] < 1:
        return {
            "status": "fail",
            "passed": False,
            "failed": True,
            "counterexample": {
                "reason": "missing_current_term_role",
                "blanket_roles": dict(blanket_roles),
            },
            "artifact_ids": [],
            "verifier_name": "etcd_raft_current_term_verifier",
            "details": {"manifest_path": str(manifest_path)},
        }

    markers = {
        "committedEntryInCurrentTerm": "committedEntryInCurrentTerm" in source_text,
        "TestLeaderOnlyCommitsLogFromCurrentTerm": "TestLeaderOnlyCommitsLogFromCurrentTerm"
        in source_text,
        "pending MsgReadIndex should be released only after first commit in current term": (
            "pending MsgReadIndex should be released only after first commit in current term"
            in normalized_source_text
        ),
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
            "verifier_name": "etcd_raft_current_term_verifier",
            "details": {"source_path": str(source_path)},
        }

    roles = manifest.get("roles", {})
    prepare_token = str(roles.get("leader_ready", "BECOME_LEADER"))
    commit_token = str(roles.get("advance_commit", "ADVANCE_COMMIT_INDEX"))
    clear_token = str(roles.get("quorum_ready", "QUORUM_MATCH"))
    stable_token = str(roles.get("current_term_entry", "CURRENT_TERM_ENTRY"))
    counter_prefix = f"{str(roles.get('replica_match', 'REPLICA_MATCH'))}_"
    required_ack_count = int(manifest.get("required_ack_count", 2))
    required_stable = bool(manifest.get("required_stable", False))

    valid_trace_count = 0
    invalid_trace_count = 0
    for trace in manifest.get("execution_traces", []):
        valid_trace_count += 1
        if not trace_is_valid(
            list(trace),
            prepare_token=prepare_token,
            commit_token=commit_token,
            clear_token=clear_token,
            required_ack_count=required_ack_count,
            stable_token=stable_token,
            required_stable=required_stable,
            counter_prefix=counter_prefix,
        ):
            return {
                "status": "fail",
                "passed": False,
                "failed": True,
                "counterexample": {"reason": "valid_trace_rejected", "trace": trace},
                "artifact_ids": [],
                "verifier_name": "etcd_raft_current_term_verifier",
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
            prepare_token=prepare_token,
            commit_token=commit_token,
            clear_token=clear_token,
            required_ack_count=required_ack_count,
            stable_token=stable_token,
            required_stable=required_stable,
            counter_prefix=counter_prefix,
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
                "verifier_name": "etcd_raft_current_term_verifier",
                "details": {"manifest_path": str(manifest_path)},
            }

    return {
        "status": "pass",
        "passed": True,
        "failed": False,
        "counterexample": None,
        "artifact_ids": [],
        "verifier_name": "etcd_raft_current_term_verifier",
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
