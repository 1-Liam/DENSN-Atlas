"""Cross-family transfer benchmark using canonical-role interface remapping."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from ..artifacts import attach_artifact_manifest, link_provenance, load_manifest
from ..graph import PersistentGraph
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..records import AtomicSymbol, Constraint, Edge, VerificationClaim
from ..system import DENSNConfig, DENSNSystem

ROOT = Path(__file__).resolve().parents[2]
LEASE_FIXTURES_DIR = ROOT / "fixtures" / "lease_lock"
VOTE_FIXTURES_DIR = ROOT / "fixtures" / "vote_majority_commit"
LEASE_VERIFIER_SCRIPT = ROOT / "verifiers" / "lease_lock_verifier.py"
VOTE_VERIFIER_SCRIPT = ROOT / "verifiers" / "vote_majority_commit_verifier.py"
LEASE_CLAIM_KIND = "lease_lock_invariant"
VOTE_CLAIM_KIND = "vote_majority_commit_invariant"


def _canonical_role(manifest: dict[str, Any], role_name: str) -> str:
    return str(manifest.get("canonical_roles", {}).get(role_name, role_name))


def build_lease_lock_graph_from_manifest(
    manifest_path: str | Path,
    *,
    prefix: str | None = None,
    mutate_count: int | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    mutate_count = int(mutate_count or manifest.get("mutate_count", 1))
    roles = manifest.get("roles", {})
    acquire_token = str(roles.get("acquire", "ACQUIRE"))
    release_token = str(roles.get("release", "RELEASE"))
    mutate_token = str(roles.get("mutate", "MUTATE"))
    epoch_token = roles.get("epoch")

    acquire_symbol = AtomicSymbol(
        id=f"{prefix}_ACQUIRE",
        name=acquire_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "acquire",
            "canonical_role": _canonical_role(manifest, "acquire"),
            "token": acquire_token,
            "task_id": manifest["task_id"],
        },
    )
    release_symbol = AtomicSymbol(
        id=f"{prefix}_RELEASE",
        name=release_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "release",
            "canonical_role": _canonical_role(manifest, "release"),
            "token": release_token,
            "task_id": manifest["task_id"],
        },
    )
    graph.add_node(acquire_symbol)
    graph.add_node(release_symbol)
    epoch_symbol = None
    if epoch_token is not None:
        epoch_symbol = AtomicSymbol(
            id=f"{prefix}_EPOCH",
            name=str(epoch_token),
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "epoch",
                "canonical_role": _canonical_role(manifest, "epoch"),
                "token": str(epoch_token),
                "task_id": manifest["task_id"],
            },
        )
        graph.add_node(epoch_symbol)

    mutate_symbols: list[AtomicSymbol] = []
    for index in range(mutate_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_MUTATE_{index + 1}",
            name=f"{mutate_token}_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "mutate",
                "canonical_role": _canonical_role(manifest, "mutate"),
                "token": mutate_token,
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        mutate_symbols.append(symbol)
        graph.add_node(symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_ACQUIRE_MUTATE",
            constraint_kind="implies",
            symbol_ids=[acquire_symbol.id, mutate_symbols[0].id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "acquire_implies_first_mutate",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_ACQUIRE_RELEASE_XOR",
            constraint_kind="xor",
            symbol_ids=[acquire_symbol.id, release_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={
                "rule": "acquire_release_mutex",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
    ]
    if epoch_symbol is not None:
        constraints.append(
            Constraint(
                id=f"{prefix}_C_MUTATE_EPOCH",
                constraint_kind="implies",
                symbol_ids=[mutate_symbols[0].id, epoch_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("failing_tests", ""),
                ],
                metadata={
                    "rule": "mutate_requires_epoch",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )
    for index, mutate_symbol in enumerate(mutate_symbols):
        successor_id = release_symbol.id
        if index + 1 < len(mutate_symbols):
            successor_id = mutate_symbols[index + 1].id
        constraints.append(
            Constraint(
                id=f"{prefix}_C_MUTATE_CHAIN_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[mutate_symbol.id, successor_id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("logs", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "mutate_progression",
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
            acquire_symbol.id,
            release_symbol.id,
            *([] if epoch_symbol is None else [epoch_symbol.id]),
            *[symbol.id for symbol in mutate_symbols],
        ],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def build_vote_majority_graph_from_manifest(
    manifest_path: str | Path,
    *,
    prefix: str | None = None,
    vote_count: int | None = None,
    required_vote_count: int | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    vote_count = int(vote_count or manifest.get("vote_count", 2))
    required_vote_count = int(required_vote_count or manifest.get("required_vote_count", 2))
    roles = manifest.get("roles", {})
    propose_token = str(roles.get("propose", "PROPOSE"))
    decide_token = str(roles.get("decide", "DECIDE"))
    waiting_token = str(roles.get("waiting", "WAITING"))
    barrier_token = str(roles.get("barrier", "BARRIER"))

    propose_symbol = AtomicSymbol(
        id=f"{prefix}_PROPOSE",
        name=propose_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "propose",
            "canonical_role": _canonical_role(manifest, "propose"),
            "token": propose_token,
            "task_id": manifest["task_id"],
        },
    )
    decide_symbol = AtomicSymbol(
        id=f"{prefix}_DECIDE",
        name=decide_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "decide",
            "canonical_role": _canonical_role(manifest, "decide"),
            "token": decide_token,
            "task_id": manifest["task_id"],
        },
    )
    waiting_symbol = AtomicSymbol(
        id=f"{prefix}_WAITING",
        name=waiting_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "waiting",
            "canonical_role": _canonical_role(manifest, "waiting"),
            "token": waiting_token,
            "task_id": manifest["task_id"],
        },
    )
    barrier_symbol = AtomicSymbol(
        id=f"{prefix}_BARRIER",
        name=barrier_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={
            "role": "barrier",
            "canonical_role": _canonical_role(manifest, "barrier"),
            "token": barrier_token,
            "task_id": manifest["task_id"],
        },
    )
    graph.add_node(propose_symbol)
    graph.add_node(decide_symbol)
    graph.add_node(waiting_symbol)
    graph.add_node(barrier_symbol)

    vote_symbols: list[AtomicSymbol] = []
    for index in range(vote_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_VOTE_{index + 1}",
            name=f"VOTE_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "vote",
                "canonical_role": _canonical_role(manifest, "vote"),
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        vote_symbols.append(symbol)
        graph.add_node(symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_DECIDE_WAITING_MUTEX",
            constraint_kind="mutex",
            symbol_ids=[decide_symbol.id, waiting_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={
                "rule": "decide_waiting_mutex",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_WAITING_PROPOSE",
            constraint_kind="implies",
            symbol_ids=[waiting_symbol.id, propose_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "waiting_requires_propose",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_DECIDE_BARRIER",
            constraint_kind="implies",
            symbol_ids=[decide_symbol.id, barrier_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("logs", ""),
            ],
            metadata={
                "rule": "decide_requires_barrier",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
    ]
    for index, vote_symbol in enumerate(vote_symbols[:required_vote_count]):
        constraints.append(
            Constraint(
                id=f"{prefix}_C_DECIDE_VOTE_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[decide_symbol.id, vote_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "decide_requires_vote",
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
            propose_symbol.id,
            decide_symbol.id,
            waiting_symbol.id,
            barrier_symbol.id,
            *[symbol.id for symbol in vote_symbols],
        ],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def _reuse_only_config() -> DENSNConfig:
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


def _register_lease_verifier(system: DENSNSystem) -> None:
    system.verifier.register_subprocess(
        LEASE_CLAIM_KIND,
        [sys.executable, str(LEASE_VERIFIER_SCRIPT)],
        cwd=str(ROOT),
        timeout_seconds=30.0,
    )


def _register_vote_verifier(system: DENSNSystem) -> None:
    system.verifier.register_subprocess(
        VOTE_CLAIM_KIND,
        [sys.executable, str(VOTE_VERIFIER_SCRIPT)],
        cwd=str(ROOT),
        timeout_seconds=30.0,
    )


def _merge_registries(*registries: OntologyRegistry) -> OntologyRegistry:
    merged = OntologyRegistry()
    for registry in registries:
        for meta_symbol_id, record in registry.records.items():
            merged.records[meta_symbol_id] = dict(record)
    return merged


def _claim_for_instantiated_meta_symbol(
    system: DENSNSystem,
    *,
    meta_symbol_id: str,
    manifest_path: str | Path,
    claim_kind: str,
    task_id: str,
) -> VerificationClaim:
    meta_symbol = system.graph.get_node(meta_symbol_id)
    return VerificationClaim(
        kind=claim_kind,
        payload={
            "task_id": task_id,
            "manifest_path": str(Path(manifest_path).resolve()),
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
            "mapping_class": meta_symbol.metadata.get("reuse_match", {}).get("mapping_class"),
        },
    )


def _run_target_case(
    *,
    case_id: str,
    manifest_path: Path,
    registry: OntologyRegistry,
    graph_builder,
    verifier_registrar,
    claim_kind: str,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)

    baseline_system = DENSNSystem(
        graph_builder(manifest_path, prefix=f"{case_id.upper()}_BASELINE"),
        _reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        graph_builder(manifest_path, prefix=f"{case_id.upper()}_REUSE"),
        _reuse_only_config(),
        registry=registry,
    )
    verifier_registrar(reuse_system)
    reuse_applications = reuse_system.apply_reusable_symbols(
        task_id=manifest["task_id"], graph=reuse_system.graph
    )
    reuse_summary = reuse_system.run_until_stable()

    verification = None
    source_record = None
    if reuse_applications:
        instantiated_id = reuse_applications[0]["instantiated_meta_symbol_id"]
        source_id = reuse_applications[0]["source_meta_symbol_id"]
        source_record = registry.records.get(source_id)
        verification_result = reuse_system.verifier.verify(
            _claim_for_instantiated_meta_symbol(
                reuse_system,
                meta_symbol_id=instantiated_id,
                manifest_path=manifest_path,
                claim_kind=claim_kind,
                task_id=manifest["task_id"],
            )
        )
        verification = verification_result.__dict__

    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        reuse_summary.get("final_psi") or 0.0
    )
    positive = (
        bool(reuse_applications)
        and bool((verification or {}).get("passed"))
        and contradiction_gain > 0.0
    )
    return {
        "case_id": case_id,
        "task_id": manifest["task_id"],
        "family": manifest["family"],
        "baseline_summary": baseline_summary,
        "reuse_summary": reuse_summary,
        "reuse_applications": reuse_applications,
        "verification": verification,
        "source_meta_symbol_id": None
        if not reuse_applications
        else reuse_applications[0]["source_meta_symbol_id"],
        "source_semantic_label": None
        if source_record is None
        else source_record.get("semantic_label"),
        "contradiction_gain": contradiction_gain,
        "positive_transfer": positive,
    }


def run_remap_transfer_benchmark(output_dir: str = "artifacts/phase6") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase6", root=ROOT)

    protocol_registry = OntologyRegistry.load(
        str(ROOT / "artifacts" / "phase1" / "formal_registry.json")
    )
    quorum_registry = OntologyRegistry.load(
        str(ROOT / "artifacts" / "phase3" / "quorum_registry.json")
    )
    combined_registry = _merge_registries(protocol_registry, quorum_registry)

    lease_case = _run_target_case(
        case_id="protocol_to_lease_lock",
        manifest_path=LEASE_FIXTURES_DIR / "target" / "manifest.json",
        registry=combined_registry,
        graph_builder=build_lease_lock_graph_from_manifest,
        verifier_registrar=_register_lease_verifier,
        claim_kind=LEASE_CLAIM_KIND,
    )
    vote_case = _run_target_case(
        case_id="quorum_to_vote_majority_commit",
        manifest_path=VOTE_FIXTURES_DIR / "target" / "manifest.json",
        registry=combined_registry,
        graph_builder=build_vote_majority_graph_from_manifest,
        verifier_registrar=_register_vote_verifier,
        claim_kind=VOTE_CLAIM_KIND,
    )

    transfer_results = [lease_case, vote_case]
    summary = {
        "artifact_version": version,
        "proof_contract": {
            "core_mode": "core_frozen",
            "core_api_version": "phase5_frozen_v1",
            "expected_core_api_version": "phase5_frozen_v1",
            "migration_note": None,
            "proposal_adapter": None,
            "verifier_stack": [
                {
                    "claim_kind": LEASE_CLAIM_KIND,
                    "verifier_type": "SubprocessVerifier",
                    "command": [sys.executable, str(LEASE_VERIFIER_SCRIPT)],
                },
                {
                    "claim_kind": VOTE_CLAIM_KIND,
                    "verifier_type": "SubprocessVerifier",
                    "command": [sys.executable, str(VOTE_VERIFIER_SCRIPT)],
                },
            ],
            "transfer_metrics": transfer_metrics_summary(transfer_results=transfer_results),
        },
        "protocol_registry_path": str(ROOT / "artifacts" / "phase1" / "formal_registry.json"),
        "quorum_registry_path": str(ROOT / "artifacts" / "phase3" / "quorum_registry.json"),
        "protocol_registry_reloaded_from_disk": True,
        "quorum_registry_reloaded_from_disk": True,
        "transfer_results": transfer_results,
        "checks": {
            "positive_within_ladder_a": bool(lease_case["positive_transfer"]),
            "positive_within_ladder_b": bool(vote_case["positive_transfer"]),
            "all_mapping_classes_role_remap": all(
                bool(result["reuse_applications"])
                and result["reuse_applications"][0].get("mapping_class") == "role_remap"
                for result in transfer_results
            ),
        },
    }
    write_json_artifact(target_dir / "remap_transfer_summary.json", summary, version=version)

    lines = [
        "# Phase 6 Remap Transfer",
        "",
        f"Artifact version: `{version['timestamp_utc']}`",
        "",
    ]
    for result in transfer_results:
        application = result["reuse_applications"][0] if result["reuse_applications"] else {}
        verification = result.get("verification") or {}
        lines.extend(
            [
                f"## {result['case_id']}",
                "",
                f"- Source label: `{result.get('source_semantic_label')}`",
                f"- Mapping class: `{application.get('mapping_class')}`",
                f"- Mapping confidence: `{application.get('mapping_confidence')}`",
                f"- Baseline final psi: `{result['baseline_summary'].get('final_psi')}`",
                f"- Reuse final psi: `{result['reuse_summary'].get('final_psi')}`",
                f"- Contradiction gain: `{result.get('contradiction_gain')}`",
                f"- Verifier passed: `{verification.get('passed')}`",
                "",
            ]
        )
    write_text_artifact(
        target_dir / "remap_transfer_report.md",
        "\n".join(lines),
        version=version,
    )
    return summary
