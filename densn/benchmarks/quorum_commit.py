"""Artifact-backed quorum-commit benchmark with non-constant interface checks."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..artifact_store import artifact_version_info, snapshot_artifact_file, write_json_artifact
from ..artifacts import attach_artifact_manifest, link_provenance, load_manifest
from ..graph import PersistentGraph
from ..lifecycle import HeldoutTaskSpec, VerifierBackedReuseEvaluator
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..records import AtomicSymbol, Constraint, Edge, VerificationClaim
from ..system import DENSNConfig, DENSNSystem

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "fixtures" / "quorum_commit"
VERIFIER_SCRIPT = ROOT / "verifiers" / "quorum_commit_verifier.py"
CLAIM_KIND = "quorum_commit_invariant"


def train_manifest_path() -> Path:
    return FIXTURES_DIR / "train" / "manifest.json"


def build_quorum_graph_from_manifest(
    manifest_path: str | Path,
    prefix: str | None = None,
    ack_count: int | None = None,
    required_ack_count: int | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    ack_count = int(ack_count or manifest.get("ack_count", 2))
    required_ack_count = int(required_ack_count or manifest.get("required_ack_count", 2))
    roles = manifest.get("roles", {})
    prepare_token = str(roles.get("prepare", "PREPARE"))
    commit_token = str(roles.get("commit", "COMMIT"))
    pending_token = str(roles.get("pending", "PENDING"))
    clear_token = str(roles.get("clear", "CLEAR"))
    stable_token = roles.get("stable")
    required_stable = bool(manifest.get("required_stable", False))

    prepare_symbol = AtomicSymbol(
        id=f"{prefix}_PREPARE",
        name=prepare_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "prepare", "token": prepare_token, "task_id": manifest["task_id"]},
    )
    commit_symbol = AtomicSymbol(
        id=f"{prefix}_COMMIT",
        name=commit_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "commit", "token": commit_token, "task_id": manifest["task_id"]},
    )
    pending_symbol = AtomicSymbol(
        id=f"{prefix}_PENDING",
        name=pending_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "pending", "token": pending_token, "task_id": manifest["task_id"]},
    )
    clear_symbol = AtomicSymbol(
        id=f"{prefix}_CLEAR",
        name=clear_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "clear", "token": clear_token, "task_id": manifest["task_id"]},
    )
    graph.add_node(prepare_symbol)
    graph.add_node(commit_symbol)
    graph.add_node(pending_symbol)
    graph.add_node(clear_symbol)
    stable_symbol = None
    if stable_token is not None:
        stable_symbol = AtomicSymbol(
            id=f"{prefix}_STABLE",
            name=str(stable_token),
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={"role": "stable", "token": str(stable_token), "task_id": manifest["task_id"]},
        )
        graph.add_node(stable_symbol)

    ack_symbols: list[AtomicSymbol] = []
    for index in range(ack_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_ACK_{index + 1}",
            name=f"ACK_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={"role": "ack", "position": index + 1, "task_id": manifest["task_id"]},
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
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("logs", ""),
            ],
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
    if required_stable and stable_symbol is not None:
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


def quorum_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=5.0,
        pathway_b_persistence_threshold=6.0,
        plateau_window=3,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=16,
        random_seed=7,
        require_verifier_for_admission=True,
        require_reuse_for_admission=True,
        min_heldout_contradiction_gain=1.0,
        max_complexity_penalty=8.0,
        candidate_labels=["CommitReady"],
    )


def no_tsl_config() -> DENSNConfig:
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


def no_conflict_memory_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.0,
        max_weight_multiplier=1.0,
        frustration_threshold=5.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=8,
        random_seed=7,
    )


def reuse_only_config() -> DENSNConfig:
    return no_tsl_config()


def heldout_specs() -> list[HeldoutTaskSpec]:
    return [
        HeldoutTaskSpec(
            task_id="quorum_commit_heldout_3",
            family="quorum_commit",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_commit_3" / "manifest.json")},
        ),
        HeldoutTaskSpec(
            task_id="quorum_commit_heldout_4",
            family="quorum_commit",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_commit_4" / "manifest.json")},
        ),
    ]


def negative_transfer_spec() -> HeldoutTaskSpec:
    return HeldoutTaskSpec(
        task_id="quorum_commit_negative_strict_3",
        family="quorum_commit",
        split="negative_transfer",
        inputs={"manifest_path": str(FIXTURES_DIR / "negative_commit_strict_3" / "manifest.json")},
    )


def _register_quorum_verifier(system: DENSNSystem) -> None:
    system.verifier.register_subprocess(
        CLAIM_KIND,
        [sys.executable, str(VERIFIER_SCRIPT)],
        cwd=str(ROOT),
        timeout_seconds=30.0,
    )


def _accepted_meta_record(
    registry: OntologyRegistry,
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    for meta_id, record in registry.records.items():
        if record["status"] == "accepted":
            return meta_id, record
    return None, None


def _graph_meta_symbol_or_fallback(system: DENSNSystem, meta_symbol) -> Any:
    if getattr(meta_symbol, "id", None) in system.graph.nodes:
        return system.graph.get_node(meta_symbol.id)
    return meta_symbol


def _training_claim(
    system: DENSNSystem,
    meta_symbol,
    task: HeldoutTaskSpec | None,
) -> VerificationClaim:
    node = _graph_meta_symbol_or_fallback(system, meta_symbol)
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": "quorum_commit_train",
            "manifest_path": str(train_manifest_path()),
            "parent_roles": system.symbol_roles(node.parent_cluster_symbol_ids),
            "blanket_roles": system.symbol_roles(node.markov_blanket_symbol_ids),
        },
    )


def _heldout_claim(
    system: DENSNSystem,
    meta_symbol,
    task: HeldoutTaskSpec | None,
) -> VerificationClaim:
    if task is None:
        raise ValueError("Held-out quorum claim requires a task specification.")
    if getattr(meta_symbol, "id", None) in system.graph.nodes:
        node = system.graph.get_node(meta_symbol.id)
        parent_roles = system.symbol_roles(node.parent_cluster_symbol_ids)
        blanket_roles = system.symbol_roles(node.markov_blanket_symbol_ids)
    else:
        record = system.registry.records.get(meta_symbol.id, {})
        signature = record.get("reuse_signature", {})
        parent_roles = list(signature.get("parent_roles", []))
        blanket_roles = list(signature.get("blanket_roles", []))
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": task.task_id,
            "manifest_path": str(task.inputs["manifest_path"]),
            "parent_roles": parent_roles,
            "blanket_roles": blanket_roles,
        },
    )


def _graph_builder(task: HeldoutTaskSpec, variant: str) -> PersistentGraph:
    manifest_path = Path(str(task.inputs["manifest_path"]))
    manifest = load_manifest(manifest_path)
    return build_quorum_graph_from_manifest(
        manifest_path,
        prefix=f"{task.task_id.upper()}_{variant.upper()}",
        ack_count=int(manifest.get("ack_count", 2)),
        required_ack_count=int(manifest.get("required_ack_count", 2)),
    )


def _run_transfer_eval(
    registry: OntologyRegistry,
    task: HeldoutTaskSpec,
) -> dict[str, Any]:
    graph = _graph_builder(task, "transfer")
    system = DENSNSystem(graph, reuse_only_config(), registry=registry)
    _register_quorum_verifier(system)
    reuse_applications = system.apply_reusable_symbols(task_id=task.task_id, graph=graph)
    summary = system.run_until_stable()
    instantiated_id = None
    if reuse_applications:
        instantiated_id = reuse_applications[0].get("instantiated_meta_symbol_id")
    meta_symbol = (
        system.graph.get_node(instantiated_id)
        if instantiated_id is not None and instantiated_id in system.graph.nodes
        else SimpleNamespace(id=next(iter(registry.records)))
    )
    verification = system.verifier.verify(_heldout_claim(system, meta_symbol, task))
    return {
        "task_id": task.task_id,
        "reuse_applications": reuse_applications,
        "summary": summary,
        "verification": verification.__dict__,
    }


def _run_ablation_eval(
    task: HeldoutTaskSpec,
    *,
    config: DENSNConfig,
    prefix: str,
) -> dict[str, Any]:
    manifest = load_manifest(str(task.inputs["manifest_path"]))
    registry = OntologyRegistry()
    system = DENSNSystem(
        build_quorum_graph_from_manifest(
            str(task.inputs["manifest_path"]),
            prefix=prefix,
            ack_count=int(manifest.get("ack_count", 2)),
            required_ack_count=int(manifest.get("required_ack_count", 2)),
        ),
        config,
        registry=registry,
    )
    summary = system.run_until_stable()
    return {
        **summary,
        "registry_lifecycle_summary": registry.lifecycle_summary(),
    }


def _interface_is_constant(record: dict[str, Any] | None) -> bool | None:
    if record is None:
        return None
    truth_table = record.get("interface_definition", {}).get("truth_table", {})
    values = set(bool(value) for value in truth_table.values())
    if not values:
        return None
    return len(values) == 1


def run_quorum_commit_benchmark(output_dir: str = "artifacts/phase3") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase3", root=ROOT)

    registry = OntologyRegistry()
    tasks = heldout_specs()

    train_manifest = train_manifest_path()
    train_graph = build_quorum_graph_from_manifest(train_manifest, prefix="TRAIN_QUORUM")
    train_system = DENSNSystem(train_graph, quorum_config(), registry=registry)
    _register_quorum_verifier(train_system)
    train_system.register_candidate_evaluator(
        VerifierBackedReuseEvaluator(
            heldout_tasks=tasks,
            graph_builder=_graph_builder,
            verifier_registrar=_register_quorum_verifier,
            training_claim_builder=_training_claim,
            heldout_claim_builder=_heldout_claim,
            baseline_config=no_tsl_config(),
            reuse_config=reuse_only_config(),
        )
    )
    train_summary = train_system.run_until_stable()

    meta_id, record = _accepted_meta_record(registry)
    transfer_results: list[dict[str, Any]] = []
    baseline_no_tsl = None
    baseline_no_conflict = None

    if meta_id is not None and record is not None:
        for task in tasks:
            transfer_results.append(_run_transfer_eval(registry, task))

        hardest = tasks[-1]
        baseline_no_tsl = _run_ablation_eval(
            hardest,
            config=no_tsl_config(),
            prefix="BASELINE_QUORUM",
        )
        baseline_no_conflict = _run_ablation_eval(
            hardest,
            config=no_conflict_memory_config(),
            prefix="NO_CONFLICT_QUORUM",
        )

    train_graph_path = target_dir / "quorum_train_graph.json"
    train_graph.save(str(train_graph_path))
    train_telemetry_path = target_dir / "quorum_train_telemetry.jsonl"
    train_system.telemetry.flush(str(train_telemetry_path))
    registry_path = target_dir / "quorum_registry.json"
    registry.save(str(registry_path))

    accepted_metrics = None if record is None else record.get("admission_metrics", {})
    lifecycle_summary = registry.lifecycle_summary()
    telemetry_summary = train_system.telemetry.summary()
    artifact_files = {
        "quorum_train_graph": snapshot_artifact_file(train_graph_path, version=version),
        "quorum_train_telemetry": snapshot_artifact_file(train_telemetry_path, version=version),
        "quorum_registry": snapshot_artifact_file(registry_path, version=version),
        "quorum_train_telemetry_summary": write_json_artifact(
            target_dir / "quorum_train_telemetry_summary.json",
            telemetry_summary,
            version=version,
        ),
    }
    summary = {
        "domain": "quorum_commit",
        "artifact_version": version,
        "proof_contract": {
            **train_system.core_contract(),
            "runtime_metrics": train_summary.get("runtime_metrics", {}),
            "lifecycle_metrics": lifecycle_summary,
            "transfer_metrics": transfer_metrics_summary(transfer_results=transfer_results),
        },
        "train_manifest_path": str(train_manifest),
        "train_summary": train_summary,
        "accepted_meta_symbol_id": meta_id,
        "accepted_record": record,
        "accepted_admission_metrics": accepted_metrics,
        "accepted_interface_is_constant": _interface_is_constant(record),
        "transfer_results": transfer_results,
        "baseline_no_tsl": baseline_no_tsl,
        "baseline_no_conflict_memory": baseline_no_conflict,
        "registry_lifecycle_summary": lifecycle_summary,
        "proposal_quarantine_summary": train_system.proposal_summary(),
    }
    artifact_files["quorum_summary"] = write_json_artifact(
        target_dir / "quorum_summary.json",
        summary,
        version=version,
    )
    write_json_artifact(
        target_dir / "quorum_artifact_index.json",
        {"artifact_version": version, "files": artifact_files},
        version=version,
    )
    return summary
