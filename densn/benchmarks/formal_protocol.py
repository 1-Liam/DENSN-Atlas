"""Artifact-backed formal protocol benchmark with external verifier-backed reuse."""

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
FIXTURES_DIR = ROOT / "fixtures" / "protocol_guard"
VERIFIER_SCRIPT = ROOT / "verifiers" / "protocol_guard_verifier.py"
CLAIM_KIND = "protocol_guard_invariant"


def train_manifest_path() -> Path:
    return FIXTURES_DIR / "train" / "manifest.json"


def build_protocol_graph_from_manifest(
    manifest_path: str | Path,
    prefix: str | None = None,
    write_count: int | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    write_count = int(write_count or manifest.get("write_count", 1))
    roles = manifest.get("roles", {})
    open_token = str(roles.get("open", "BEGIN"))
    close_token = str(roles.get("close", "END"))
    write_token = str(roles.get("action", "WRITE"))

    open_symbol = AtomicSymbol(
        id=f"{prefix}_BEGIN",
        name=open_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "open", "token": open_token, "task_id": manifest["task_id"]},
    )
    close_symbol = AtomicSymbol(
        id=f"{prefix}_END",
        name=close_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "close", "token": close_token, "task_id": manifest["task_id"]},
    )
    graph.add_node(open_symbol)
    graph.add_node(close_symbol)

    write_symbols: list[AtomicSymbol] = []
    for index in range(write_count):
        symbol = AtomicSymbol(
            id=f"{prefix}_WRITE_{index + 1}",
            name=f"{write_token}_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "write",
                "token": write_token,
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        write_symbols.append(symbol)
        graph.add_node(symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_BEGIN_WRITE",
            constraint_kind="implies",
            symbol_ids=[open_symbol.id, write_symbols[0].id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "begin_implies_first_write",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_BEGIN_END_XOR",
            constraint_kind="xor",
            symbol_ids=[open_symbol.id, close_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={"rule": "begin_end_mutex", "manifest_path": artifact_info["manifest_path"]},
        ),
    ]
    for index, write_symbol in enumerate(write_symbols):
        successor_id = close_symbol.id
        if index + 1 < len(write_symbols):
            successor_id = write_symbols[index + 1].id
        constraints.append(
            Constraint(
                id=f"{prefix}_C_WRITE_CHAIN_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[write_symbol.id, successor_id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("logs", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "write_progression",
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
        [open_symbol.id, close_symbol.id, *[symbol.id for symbol in write_symbols]],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def protocol_config() -> DENSNConfig:
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
        max_complexity_penalty=6.0,
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
            task_id="protocol_guard_heldout_3",
            family="protocol_guard",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_guard_3" / "manifest.json")},
        ),
        HeldoutTaskSpec(
            task_id="protocol_guard_heldout_4",
            family="protocol_guard",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_guard_4" / "manifest.json")},
        ),
    ]


def _register_protocol_verifier(system: DENSNSystem) -> None:
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


def _training_claim(
    system: DENSNSystem,
    meta_symbol,
    task: HeldoutTaskSpec | None,
) -> VerificationClaim:
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": "protocol_guard_train",
            "manifest_path": str(train_manifest_path()),
            "parent_roles": system.symbol_roles(meta_symbol.parent_cluster_symbol_ids),
            "blanket_roles": system.symbol_roles(meta_symbol.markov_blanket_symbol_ids),
        },
    )


def _heldout_claim(
    system: DENSNSystem,
    meta_symbol,
    task: HeldoutTaskSpec | None,
) -> VerificationClaim:
    if task is None:
        raise ValueError("Held-out protocol claim requires a task specification.")
    record = system.registry.records.get(meta_symbol.id, {})
    signature = record.get("reuse_signature", {})
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": task.task_id,
            "manifest_path": str(task.inputs["manifest_path"]),
            "parent_roles": list(signature.get("parent_roles", [])),
            "blanket_roles": list(signature.get("blanket_roles", [])),
        },
    )


def _graph_builder(task: HeldoutTaskSpec, variant: str) -> PersistentGraph:
    manifest_path = Path(str(task.inputs["manifest_path"]))
    manifest = load_manifest(manifest_path)
    return build_protocol_graph_from_manifest(
        manifest_path,
        prefix=f"{task.task_id.upper()}_{variant.upper()}",
        write_count=int(manifest.get("write_count", 1)),
    )


def _run_transfer_eval(
    registry: OntologyRegistry,
    task: HeldoutTaskSpec,
) -> dict[str, Any]:
    graph = _graph_builder(task, "transfer")
    system = DENSNSystem(graph, reuse_only_config(), registry=registry)
    _register_protocol_verifier(system)
    reuse_applications = system.apply_reusable_symbols(task_id=task.task_id, graph=graph)
    summary = system.run_until_stable()
    meta_id, record = _accepted_meta_record(registry)
    if meta_id is None or record is None:
        raise RuntimeError("Transfer evaluation requires an accepted registry symbol.")
    verification = system.verifier.verify(_heldout_claim(system, SimpleNamespace(id=meta_id), task))
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
        build_protocol_graph_from_manifest(
            str(task.inputs["manifest_path"]),
            prefix=prefix,
            write_count=int(manifest.get("write_count", 1)),
        ),
        config,
        registry=registry,
    )
    summary = system.run_until_stable()
    return {
        **summary,
        "registry_lifecycle_summary": registry.lifecycle_summary(),
    }


def run_formal_protocol_benchmark(output_dir: str = "artifacts/phase1") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase1", root=ROOT)

    registry = OntologyRegistry()
    tasks = heldout_specs()

    train_manifest = train_manifest_path()
    train_graph = build_protocol_graph_from_manifest(train_manifest, prefix="TRAIN_PROTOCOL")
    train_system = DENSNSystem(train_graph, protocol_config(), registry=registry)
    _register_protocol_verifier(train_system)
    train_system.register_candidate_evaluator(
        VerifierBackedReuseEvaluator(
            heldout_tasks=tasks,
            graph_builder=_graph_builder,
            verifier_registrar=_register_protocol_verifier,
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
            prefix="BASELINE_PROTOCOL",
        )
        baseline_no_conflict = _run_ablation_eval(
            hardest,
            config=no_conflict_memory_config(),
            prefix="NO_CONFLICT_PROTOCOL",
        )

    train_graph_path = target_dir / "formal_train_graph.json"
    train_graph.save(str(train_graph_path))
    train_telemetry_path = target_dir / "formal_train_telemetry.jsonl"
    train_system.telemetry.flush(str(train_telemetry_path))
    registry_path = target_dir / "formal_registry.json"
    registry.save(str(registry_path))

    accepted_metrics = None if record is None else record.get("admission_metrics", {})
    lifecycle_summary = registry.lifecycle_summary()
    telemetry_summary = train_system.telemetry.summary()
    artifact_files = {
        "formal_train_graph": snapshot_artifact_file(train_graph_path, version=version),
        "formal_train_telemetry": snapshot_artifact_file(train_telemetry_path, version=version),
        "formal_registry": snapshot_artifact_file(registry_path, version=version),
        "formal_train_telemetry_summary": write_json_artifact(
            target_dir / "formal_train_telemetry_summary.json",
            telemetry_summary,
            version=version,
        ),
    }
    accountability = {
        "heldout_case_count": len(tasks),
        "heldout_task_ids": [task.task_id for task in tasks],
        "accepted_candidate_count": lifecycle_summary["accepted"],
        "rejected_candidate_count": lifecycle_summary["rejected"],
        "retired_candidate_count": lifecycle_summary["retired"],
        "rollback_count": telemetry_summary.get("event_type_counts", {}).get("tsl_reject", 0),
        "accepted_tsl_events": telemetry_summary.get("event_type_counts", {}).get("tsl_event", 0),
        "retirement_events": len(lifecycle_summary.get("retired_ids", [])),
    }
    summary = {
        "domain": "protocol_guard",
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
        "transfer_results": transfer_results,
        "baseline_no_tsl": baseline_no_tsl,
        "baseline_no_conflict_memory": baseline_no_conflict,
        "registry_lifecycle_summary": lifecycle_summary,
        "accountability": accountability,
        "proposal_quarantine_summary": train_system.proposal_summary(),
    }
    artifact_files["formal_summary"] = write_json_artifact(
        target_dir / "formal_summary.json",
        summary,
        version=version,
    )
    write_json_artifact(
        target_dir / "formal_artifact_index.json",
        {"artifact_version": version, "files": artifact_files},
        version=version,
    )
    return summary
