"""Support helpers for the unified final-proof gauntlet."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from ..artifacts import attach_artifact_manifest, link_provenance, load_manifest
from ..graph import PersistentGraph
from ..records import AtomicSymbol, Constraint, Edge, Evidence, VerificationClaim, VerifierArtifact
from ..system import DENSNConfig, DENSNSystem


def reuse_only_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=999.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=8,
        random_seed=7,
    )


def canonical_role(manifest: dict[str, Any], role_name: str) -> str:
    return str(manifest.get("canonical_roles", {}).get(role_name, role_name))


def find_role_key(manifest: dict[str, Any], canonical: str, fallbacks: list[str]) -> str:
    for role_name, mapped in manifest.get("canonical_roles", {}).items():
        if str(mapped) == canonical:
            return str(role_name)
    for role_name in fallbacks:
        if role_name in manifest.get("roles", {}):
            return role_name
    raise KeyError(f"Missing canonical role {canonical!r} in {manifest.get('task_id')!r}.")


def first_count(manifest: dict[str, Any], *names: str, default: int = 1) -> int:
    for name in names:
        if name in manifest:
            return int(manifest[name])
    return default


def build_window_family_graph_from_manifest(
    manifest_path: str | Path,
    *,
    prefix: str | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    roles = manifest.get("roles", {})
    open_key = find_role_key(manifest, "open", ["open", "acquire", "start"])
    close_key = find_role_key(manifest, "close", ["close", "release", "finish"])
    action_key = find_role_key(manifest, "write", ["action", "mutate", "update"])
    epoch_key = None
    if any(str(value) == "epoch" for value in manifest.get("canonical_roles", {}).values()):
        epoch_key = find_role_key(manifest, "epoch", ["epoch"])

    action_count = first_count(manifest, "write_count", "mutate_count", "update_count", default=1)

    def _symbol(role_key: str, token: str, *, suffix: str = "") -> AtomicSymbol:
        identifier = f"{prefix}_{role_key.upper()}{suffix}"
        metadata: dict[str, Any] = {
            "role": role_key,
            "canonical_role": canonical_role(manifest, role_key),
            "token": token,
            "task_id": manifest["task_id"],
        }
        if suffix:
            metadata["position"] = int(suffix.replace("_", ""))
        return AtomicSymbol(
            id=identifier,
            name=token if not suffix else f"{token}{suffix}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata=metadata,
        )

    open_symbol = _symbol(open_key, str(roles.get(open_key)))
    close_symbol = _symbol(close_key, str(roles.get(close_key)))
    graph.add_node(open_symbol)
    graph.add_node(close_symbol)

    epoch_symbol = None
    if epoch_key is not None:
        epoch_symbol = _symbol(epoch_key, str(roles.get(epoch_key)))
        graph.add_node(epoch_symbol)

    action_symbols: list[AtomicSymbol] = []
    action_token = str(roles.get(action_key))
    for index in range(action_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_{action_key.upper()}_{index + 1}",
            name=f"{action_token}_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": action_key,
                "canonical_role": canonical_role(manifest, action_key),
                "token": action_token,
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        action_symbols.append(symbol)
        graph.add_node(symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_OPEN_ACTION",
            constraint_kind="implies",
            symbol_ids=[open_symbol.id, action_symbols[0].id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "open_implies_first_action",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_OPEN_CLOSE_XOR",
            constraint_kind="xor",
            symbol_ids=[open_symbol.id, close_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={"rule": "open_close_mutex", "manifest_path": artifact_info["manifest_path"]},
        ),
    ]
    if epoch_symbol is not None:
        constraints.append(
            Constraint(
                id=f"{prefix}_C_ACTION_EPOCH",
                constraint_kind="implies",
                symbol_ids=[action_symbols[0].id, epoch_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("failing_tests", ""),
                ],
                metadata={
                    "rule": "action_requires_epoch",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )
    for index, action_symbol in enumerate(action_symbols):
        successor_id = (
            close_symbol.id if index + 1 >= len(action_symbols) else action_symbols[index + 1].id
        )
        constraints.append(
            Constraint(
                id=f"{prefix}_C_ACTION_CHAIN_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[action_symbol.id, successor_id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("logs", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "action_progression",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )

    for constraint in constraints:
        graph.add_node(constraint)
        for symbol_id in constraint.symbol_ids:
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=symbol_id,
                    dst_id=constraint.id,
                    edge_kind="participates_in",
                )
            )

    symbol_evidence = [
        evidence_ids[key]
        for key in ("natural_language_spec", "formal_spec", "source_code_path", "logs")
        if key in evidence_ids
    ]
    constraint_evidence = [
        evidence_ids[key]
        for key in ("formal_spec", "failing_tests", "counterexamples", "execution_traces")
        if key in evidence_ids
    ]
    link_provenance(
        graph,
        symbol_evidence,
        [
            open_symbol.id,
            close_symbol.id,
            *([] if epoch_symbol is None else [epoch_symbol.id]),
            *[symbol.id for symbol in action_symbols],
        ],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def build_commit_family_graph_from_manifest(
    manifest_path: str | Path,
    *,
    prefix: str | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    roles = manifest.get("roles", {})
    prepare_key = find_role_key(manifest, "prepare", ["prepare", "propose", "stage"])
    commit_key = find_role_key(manifest, "commit", ["commit", "decide", "publish"])
    pending_key = find_role_key(manifest, "pending", ["pending", "waiting", "queued"])
    ack_key = find_role_key(manifest, "ack", ["ack", "vote", "replica"])
    clear_key = find_role_key(manifest, "clear", ["clear", "barrier"])
    stable_key = None
    if (
        any(str(value) == "stable" for value in manifest.get("canonical_roles", {}).values())
        or "stable" in roles
    ):
        stable_key = find_role_key(manifest, "stable", ["stable"])

    ack_count = first_count(manifest, "ack_count", "vote_count", "replica_count", default=2)
    required_ack_count = first_count(
        manifest,
        "required_ack_count",
        "required_vote_count",
        "required_replica_count",
        default=2,
    )

    def _symbol(role_key: str, token: str) -> AtomicSymbol:
        return AtomicSymbol(
            id=f"{prefix}_{role_key.upper()}",
            name=token,
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": role_key,
                "canonical_role": canonical_role(manifest, role_key),
                "token": token,
                "task_id": manifest["task_id"],
            },
        )

    prepare_symbol = _symbol(prepare_key, str(roles.get(prepare_key)))
    commit_symbol = _symbol(commit_key, str(roles.get(commit_key)))
    pending_symbol = _symbol(pending_key, str(roles.get(pending_key)))
    clear_symbol = _symbol(clear_key, str(roles.get(clear_key)))
    for symbol in (prepare_symbol, commit_symbol, pending_symbol, clear_symbol):
        graph.add_node(symbol)

    stable_symbol = None
    if stable_key is not None:
        stable_symbol = _symbol(stable_key, str(roles.get(stable_key)))
        graph.add_node(stable_symbol)

    ack_symbols: list[AtomicSymbol] = []
    ack_token = str(roles.get(ack_key))
    for index in range(ack_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_{ack_key.upper()}_{index + 1}",
            name=f"{ack_token}_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": ack_key,
                "canonical_role": canonical_role(manifest, ack_key),
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        ack_symbols.append(symbol)
        graph.add_node(symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_COMMIT_PENDING_MUTEX",
            constraint_kind="mutex",
            symbol_ids=[commit_symbol.id, pending_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={
                "rule": "commit_pending_mutex",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_PENDING_PREPARE",
            constraint_kind="implies",
            symbol_ids=[pending_symbol.id, prepare_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "pending_requires_prepare",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_COMMIT_CLEAR",
            constraint_kind="implies",
            symbol_ids=[commit_symbol.id, clear_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[evidence_ids.get("formal_spec", ""), evidence_ids.get("logs", "")],
            metadata={
                "rule": "commit_requires_clear",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
    ]
    for index, ack_symbol in enumerate(ack_symbols[:required_ack_count]):
        constraints.append(
            Constraint(
                id=f"{prefix}_C_COMMIT_ACK_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[commit_symbol.id, ack_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "commit_requires_ack",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )
    if stable_symbol is not None and bool(manifest.get("required_stable", False)):
        constraints.append(
            Constraint(
                id=f"{prefix}_C_COMMIT_STABLE",
                constraint_kind="implies",
                symbol_ids=[commit_symbol.id, stable_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("execution_traces", ""),
                ],
                metadata={
                    "rule": "commit_requires_stable",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )

    for constraint in constraints:
        graph.add_node(constraint)
        for symbol_id in constraint.symbol_ids:
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=symbol_id,
                    dst_id=constraint.id,
                    edge_kind="participates_in",
                )
            )

    symbol_evidence = [
        evidence_ids[key]
        for key in ("natural_language_spec", "formal_spec", "source_code_path", "logs")
        if key in evidence_ids
    ]
    constraint_evidence = [
        evidence_ids[key]
        for key in ("formal_spec", "failing_tests", "counterexamples", "execution_traces")
        if key in evidence_ids
    ]
    link_provenance(
        graph,
        symbol_evidence,
        [
            prepare_symbol.id,
            commit_symbol.id,
            pending_symbol.id,
            clear_symbol.id,
            *([] if stable_symbol is None else [stable_symbol.id]),
            *[symbol.id for symbol in ack_symbols],
        ],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def register_secondary_verifiers(
    system: DENSNSystem,
    *,
    claim_kind: str,
    subprocess_command: list[str],
    cwd: str,
) -> None:
    system.verifier.register_subprocess(
        claim_kind, subprocess_command, cwd=cwd, timeout_seconds=30.0
    )
    system.verifier.register_role_count(claim_kind)
    system.verifier.register_trace_contract(claim_kind)


def required_counts_from_record(record: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    signature = record.get("reuse_signature", {})
    parent = Counter(signature.get("canonical_parent_roles", signature.get("parent_roles", [])))
    blanket = Counter(signature.get("canonical_blanket_roles", signature.get("blanket_roles", [])))
    return dict(parent), dict(blanket)


def window_trace_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    roles = manifest.get("roles", {})
    open_key = find_role_key(manifest, "open", ["open", "acquire", "start"])
    close_key = find_role_key(manifest, "close", ["close", "release", "finish"])
    action_key = find_role_key(manifest, "write", ["action", "mutate", "update"])
    return {
        "type": "window_guard",
        "open_token": str(roles.get(open_key)),
        "close_token": str(roles.get(close_key)),
        "action_token": str(roles.get(action_key)),
    }


def commit_trace_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    roles = manifest.get("roles", {})
    prepare_key = find_role_key(manifest, "prepare", ["prepare", "propose", "stage"])
    commit_key = find_role_key(manifest, "commit", ["commit", "decide", "publish"])
    clear_key = find_role_key(manifest, "clear", ["clear", "barrier"])
    ack_key = find_role_key(manifest, "ack", ["ack", "vote", "replica"])
    stable_key = None
    if (
        any(str(value) == "stable" for value in manifest.get("canonical_roles", {}).values())
        or "stable" in roles
    ):
        stable_key = find_role_key(manifest, "stable", ["stable"])
    return {
        "type": "gated_commit",
        "prepare_token": str(roles.get(prepare_key)),
        "commit_token": str(roles.get(commit_key)),
        "clear_token": str(roles.get(clear_key)),
        "counter_prefix": f"{str(roles.get(ack_key))}_",
        "required_counter_count": first_count(
            manifest,
            "required_ack_count",
            "required_vote_count",
            "required_replica_count",
            default=2,
        ),
        "stable_token": None if stable_key is None else str(roles.get(stable_key)),
        "required_stable": bool(manifest.get("required_stable", False)),
    }


def trace_contract_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    family = str(manifest.get("family", ""))
    canonical_roles = {str(value) for value in manifest.get("canonical_roles", {}).values()}
    role_keys = {str(key) for key in manifest.get("roles", {}).keys()}
    if family in {
        "quorum_commit",
        "vote_majority_commit",
        "replication_barrier",
        "consensus_readiness",
    }:
        return commit_trace_contract(manifest)
    if family in {
        "protocol_guard",
        "lease_lock",
        "session_epoch",
        "transaction_window",
    }:
        return window_trace_contract(manifest)
    if {"prepare", "commit", "ack", "clear"} & canonical_roles:
        return commit_trace_contract(manifest)
    if {"prepare", "commit", "pending", "ack", "clear", "stable"} & role_keys:
        return commit_trace_contract(manifest)
    return window_trace_contract(manifest)


def claim_for_meta_symbol(
    system: DENSNSystem,
    *,
    meta_symbol_id: str,
    manifest_path: Path,
    claim_kind: str,
    record: dict[str, Any],
) -> VerificationClaim:
    meta_symbol = system.graph.get_node(meta_symbol_id)
    manifest = load_manifest(manifest_path)
    required_parent, required_blanket = required_counts_from_record(record)
    trace_contract = trace_contract_for_manifest(manifest)
    return VerificationClaim(
        kind=claim_kind,
        payload={
            "task_id": manifest["task_id"],
            "manifest_path": str(manifest_path.resolve()),
            "parent_roles": system.symbol_roles(meta_symbol.parent_cluster_symbol_ids),
            "blanket_roles": system.symbol_roles(meta_symbol.markov_blanket_symbol_ids),
            "canonical_parent_roles": system.symbol_roles_with_field(
                meta_symbol.parent_cluster_symbol_ids,
                role_field="canonical_role",
            ),
            "canonical_blanket_roles": system.symbol_roles_with_field(
                meta_symbol.markov_blanket_symbol_ids,
                role_field="canonical_role",
            ),
            "required_parent_role_counts": required_parent,
            "required_blanket_role_counts": required_blanket,
            "trace_contract": trace_contract,
            "mapping_class": meta_symbol.metadata.get("reuse_match", {}).get("mapping_class"),
        },
    )


def claim_without_application(
    *,
    manifest_path: Path,
    claim_kind: str,
    record: dict[str, Any],
) -> VerificationClaim:
    manifest = load_manifest(manifest_path)
    signature = record.get("reuse_signature", {})
    required_parent, required_blanket = required_counts_from_record(record)
    trace_contract = trace_contract_for_manifest(manifest)
    return VerificationClaim(
        kind=claim_kind,
        payload={
            "task_id": manifest["task_id"],
            "manifest_path": str(manifest_path.resolve()),
            "parent_roles": list(signature.get("parent_roles", [])),
            "blanket_roles": list(signature.get("blanket_roles", [])),
            "canonical_parent_roles": list(
                signature.get("canonical_parent_roles", signature.get("parent_roles", []))
            ),
            "canonical_blanket_roles": list(
                signature.get("canonical_blanket_roles", signature.get("blanket_roles", []))
            ),
            "required_parent_role_counts": required_parent,
            "required_blanket_role_counts": required_blanket,
            "trace_contract": trace_contract,
            "mapping_class": "invalid_transfer",
        },
    )


def integrate_secondary_verifier_evidence(
    system: DENSNSystem,
    *,
    node_id: str,
    results: list[Any],
) -> None:
    pass_count = sum(1 for result in results if result.passed)
    fail_count = sum(1 for result in results if result.failed)
    for result in results:
        artifact = VerifierArtifact(
            id=system.graph.next_id("verifier"),
            verifier_name=result.verifier_name,
            artifact_kind="verification_result",
            status=result.status,
            cost=result.cost,
            counterexample_ref=None if result.counterexample is None else "inline",
            metadata={"details": result.details},
        )
        system.graph.add_node(artifact)
        system.graph.add_edge(
            Edge(
                id=system.graph.next_id("edge"),
                src_id=artifact.id,
                dst_id=node_id,
                edge_kind="supports" if result.passed else "contradicts",
            )
        )
    if pass_count and fail_count:
        disagreement = Evidence(
            id=system.graph.next_id("evidence"),
            kind="verifier_disagreement",
            content_ref=f"pass={pass_count};fail={fail_count}",
            source="verifier_bus",
            metadata={"pass_count": pass_count, "fail_count": fail_count},
        )
        system.graph.add_node(disagreement)
        system.graph.add_edge(
            Edge(
                id=system.graph.next_id("edge"),
                src_id=disagreement.id,
                dst_id=node_id,
                edge_kind="contradicts",
            )
        )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def request_groq_json(prompt: str) -> dict[str, Any]:
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is required for live model baselines.")
    from ..transformer import GroqChatTransformerAdapter

    adapter = GroqChatTransformerAdapter(
        model=os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b",
        temperature=0.0,
        max_completion_tokens=1000,
        response_format_mode="json_object",
    )
    return adapter.request_json_object(prompt)


def model_baseline_prompt(
    source_manifest: dict[str, Any],
    target_manifest: dict[str, Any] | None,
    *,
    with_retrieval: bool,
) -> str:
    sections = [
        "Propose one reusable abstraction hypothesis for the source formal task.",
        "Return JSON with keys: abstain, label, canonical_parent_roles, canonical_blanket_roles, rationale.",
        "Canonical roles may only come from: open, close, write, prepare, commit, pending, ack, clear, stable, epoch.",
        f"Source task: {source_manifest.get('task_id')}",
        f"Source description: {source_manifest.get('description')}",
        f"Source natural language spec: {source_manifest.get('natural_language_spec')}",
        "Source formal rules:",
        *[f"- {rule}" for rule in source_manifest.get("formal_spec", {}).get("rules", [])],
    ]
    if with_retrieval and target_manifest is not None:
        sections.extend(
            [
                f"Target task: {target_manifest.get('task_id')}",
                f"Target description: {target_manifest.get('description')}",
                f"Target natural language spec: {target_manifest.get('natural_language_spec')}",
                "Target formal rules:",
                *[f"- {rule}" for rule in target_manifest.get("formal_spec", {}).get("rules", [])],
            ]
        )
    sections.append(
        '{"abstain": false, "label": "WriteGuard", "canonical_parent_roles": ["open", "close"], "canonical_blanket_roles": ["write", "write"], "rationale": "..."}'
    )
    return "\n".join(sections)


def runtime_row_fields(summary: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(summary.get("runtime_metrics", {}))
    registry = dict(summary.get("registry", {}))
    return {
        "cycles_to_first_accepted_symbol": runtime.get("cycles_to_first_accepted_symbol"),
        "verifier_calls_to_acceptance": runtime.get("verifier_calls_to_acceptance"),
        "rollback_count": runtime.get("rollback_count_before_acceptance"),
        "retirement_count": int(registry.get("retired", 0)),
        "false_candidate_count": runtime.get("false_candidate_count_before_acceptance"),
        "contradiction_before_acceptance": runtime.get("contradiction_before_acceptance"),
    }


def row(
    *,
    system_name: str,
    family: str,
    target_family: str,
    case_kind: str,
    mapping_class: str | None,
    baseline_final_psi: float | None,
    transfer_final_psi: float | None,
    contradiction_gain: float | None,
    verifier_results: list[Any] | None,
    verifier_stack: list[dict[str, Any]],
    source_runtime_metrics: dict[str, Any],
    accepted_interface_is_constant: bool | None,
    proposal_adapter: str | None,
    artifact_version: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verifier_results = verifier_results or []
    verifier_status = "missing"
    verifier_reason = None
    if verifier_results:
        primary = verifier_results[0]
        verifier_status = primary.status
        if primary.counterexample is not None:
            verifier_reason = primary.counterexample.get("reason")
    data = {
        **source_runtime_metrics,
        "system": system_name,
        "family": family,
        "target_family": target_family,
        "case_kind": case_kind,
        "mapping_class": mapping_class,
        "baseline_final_psi": baseline_final_psi,
        "transfer_final_psi": transfer_final_psi,
        "contradiction_gain": contradiction_gain,
        "verifier_status": verifier_status,
        "verifier_reason": verifier_reason,
        "verifier_results": [result.__dict__ for result in verifier_results],
        "verifier_stack": verifier_stack,
        "proposal_adapter": proposal_adapter,
        "accepted_interface_is_constant": accepted_interface_is_constant,
        "artifact_version": artifact_version,
        "git_sha": artifact_version.get("git_sha"),
    }
    if extra:
        data.update(extra)
    return data
