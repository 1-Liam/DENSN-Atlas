"""Artifact-backed credit-window benchmark outside the existing proof ladders."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from ..artifacts import attach_artifact_manifest, link_provenance
from ..graph import PersistentGraph
from ..lifecycle import HeldoutTaskSpec, VerifierBackedReuseEvaluator
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..records import AtomicSymbol, Constraint, Edge, VerificationClaim
from ..system import DENSNConfig, DENSNSystem
from .gauntlet_support import load_json, model_baseline_prompt, request_groq_json

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "fixtures" / "credit_window"
VERIFIER_SCRIPT = ROOT / "verifiers" / "credit_window_verifier.py"
CLAIM_KIND = "credit_window_invariant"


def train_manifest_path() -> Path:
    return FIXTURES_DIR / "train" / "manifest.json"


def heldout_specs() -> list[HeldoutTaskSpec]:
    return [
        HeldoutTaskSpec(
            task_id="credit_window_heldout_3",
            family="credit_window",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_credit_3" / "manifest.json")},
        )
    ]


def negative_transfer_spec() -> HeldoutTaskSpec:
    return HeldoutTaskSpec(
        task_id="credit_window_negative_wrap",
        family="credit_window",
        split="negative_transfer",
        inputs={"manifest_path": str(FIXTURES_DIR / "negative_credit_wrap" / "manifest.json")},
    )


def build_credit_window_graph_from_manifest(
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
    grant_token = str(roles.get("grant", "GRANT"))
    revoke_token = str(roles.get("revoke", "REVOKE"))
    charge_token = str(roles.get("charge", "CHARGE"))
    balance_token = None if "balance" not in roles else str(roles.get("balance"))
    charge_count = int(manifest.get("write_count", 1))

    grant_symbol = AtomicSymbol(
        id=f"{prefix}_GRANT",
        name=grant_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "grant", "canonical_role": "open", "task_id": manifest["task_id"]},
    )
    revoke_symbol = AtomicSymbol(
        id=f"{prefix}_REVOKE",
        name=revoke_token,
        truth_value=True,
        locked=True,
        provenance_ids=list(evidence_ids.values()),
        metadata={"role": "revoke", "canonical_role": "close", "task_id": manifest["task_id"]},
    )
    balance_symbol = None
    graph.add_node(grant_symbol)
    graph.add_node(revoke_symbol)
    if balance_token is not None:
        balance_symbol = AtomicSymbol(
            id=f"{prefix}_BALANCE",
            name=balance_token,
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={"role": "balance", "canonical_role": "epoch", "task_id": manifest["task_id"]},
        )
        graph.add_node(balance_symbol)

    charge_symbols: list[AtomicSymbol] = []
    for index in range(charge_count):
        charge_symbol = AtomicSymbol(
            id=f"{prefix}_CHARGE_{index + 1}",
            name=f"{charge_token}_{index + 1}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "charge",
                "canonical_role": "write",
                "position": index + 1,
                "task_id": manifest["task_id"],
            },
        )
        charge_symbols.append(charge_symbol)
        graph.add_node(charge_symbol)

    constraints = [
        Constraint(
            id=f"{prefix}_C_GRANT_REVOKE_XOR",
            constraint_kind="xor",
            symbol_ids=[grant_symbol.id, revoke_symbol.id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("failing_tests", ""),
            ],
            metadata={
                "rule": "grant_revoke_mutex",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
        Constraint(
            id=f"{prefix}_C_GRANT_CHARGE",
            constraint_kind="implies",
            symbol_ids=[grant_symbol.id, charge_symbols[0].id],
            base_weight=1.0,
            weight=1.0,
            max_weight=16.0,
            provenance_ids=[
                evidence_ids.get("formal_spec", ""),
                evidence_ids.get("natural_language_spec", ""),
            ],
            metadata={
                "rule": "grant_implies_charge",
                "manifest_path": artifact_info["manifest_path"],
            },
        ),
    ]
    if balance_symbol is not None:
        constraints.append(
            Constraint(
                id=f"{prefix}_C_GRANT_BALANCE",
                constraint_kind="implies",
                symbol_ids=[grant_symbol.id, balance_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("execution_traces", ""),
                ],
                metadata={
                    "rule": "grant_implies_balance",
                    "manifest_path": artifact_info["manifest_path"],
                },
            )
        )
    for index, charge_symbol in enumerate(charge_symbols):
        if balance_symbol is not None:
            constraints.append(
                Constraint(
                    id=f"{prefix}_C_CHARGE_BALANCE_{index + 1}",
                    constraint_kind="implies",
                    symbol_ids=[charge_symbol.id, balance_symbol.id],
                    base_weight=1.0,
                    weight=1.0,
                    max_weight=16.0,
                    provenance_ids=[
                        evidence_ids.get("formal_spec", ""),
                        evidence_ids.get("logs", ""),
                    ],
                    metadata={
                        "rule": "charge_requires_balance",
                        "manifest_path": artifact_info["manifest_path"],
                    },
                )
            )
        successor_id = (
            revoke_symbol.id if index + 1 >= len(charge_symbols) else charge_symbols[index + 1].id
        )
        constraints.append(
            Constraint(
                id=f"{prefix}_C_CHARGE_CHAIN_{index + 1}",
                constraint_kind="implies",
                symbol_ids=[charge_symbol.id, successor_id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("execution_traces", ""),
                    evidence_ids.get("counterexamples", ""),
                ],
                metadata={
                    "rule": "charge_progression",
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
            grant_symbol.id,
            revoke_symbol.id,
            *([] if balance_symbol is None else [balance_symbol.id]),
            *[symbol.id for symbol in charge_symbols],
        ],
    )
    link_provenance(graph, constraint_evidence, [constraint.id for constraint in constraints])
    return graph


def credit_window_config() -> DENSNConfig:
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
        candidate_labels=["CreditLive"],
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


def _register_verifier(system: DENSNSystem) -> None:
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
        if record.get("status") == "accepted":
            return meta_id, record
    return None, None


def _graph_meta_symbol_or_fallback(system: DENSNSystem, meta_symbol) -> Any:
    if getattr(meta_symbol, "id", None) in system.graph.nodes:
        return system.graph.get_node(meta_symbol.id)
    return meta_symbol


def _training_claim(
    system: DENSNSystem, meta_symbol, task: HeldoutTaskSpec | None
) -> VerificationClaim:
    node = _graph_meta_symbol_or_fallback(system, meta_symbol)
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": "credit_window_train",
            "manifest_path": str(train_manifest_path()),
            "parent_roles": system.symbol_roles_with_field(
                node.parent_cluster_symbol_ids,
                role_field="canonical_role",
            ),
            "blanket_roles": system.symbol_roles_with_field(
                node.markov_blanket_symbol_ids,
                role_field="canonical_role",
            ),
        },
    )


def _heldout_claim(
    system: DENSNSystem, meta_symbol, task: HeldoutTaskSpec | None
) -> VerificationClaim:
    if task is None:
        raise ValueError("Held-out credit-window claim requires a task specification.")
    if getattr(meta_symbol, "id", None) in system.graph.nodes:
        node = system.graph.get_node(meta_symbol.id)
        parent_roles = system.symbol_roles_with_field(
            node.parent_cluster_symbol_ids,
            role_field="canonical_role",
        )
        blanket_roles = system.symbol_roles_with_field(
            node.markov_blanket_symbol_ids,
            role_field="canonical_role",
        )
    else:
        record = system.registry.records.get(meta_symbol.id, {})
        signature = record.get("reuse_signature", {})
        parent_roles = list(signature.get("canonical_parent_roles", []))
        blanket_roles = list(signature.get("canonical_blanket_roles", []))
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
            "task_id": task.task_id,
            "manifest_path": str(task.inputs["manifest_path"]),
            "parent_roles": parent_roles,
            "blanket_roles": blanket_roles,
        },
    )


def _graph_builder(task: HeldoutTaskSpec, variant: str):
    manifest_path = Path(str(task.inputs["manifest_path"]))
    return build_credit_window_graph_from_manifest(
        manifest_path,
        prefix=f"{task.task_id.upper()}_{variant.upper()}",
    )


def _run_transfer_eval(registry: OntologyRegistry, task: HeldoutTaskSpec) -> dict[str, Any]:
    baseline_system = DENSNSystem(
        _graph_builder(task, "baseline"), no_tsl_config(), registry=OntologyRegistry()
    )
    baseline_summary = baseline_system.run_until_stable()

    graph = _graph_builder(task, "transfer")
    system = DENSNSystem(graph, reuse_only_config(), registry=registry)
    _register_verifier(system)
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
    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        summary.get("final_psi") or 0.0
    )
    return {
        "task_id": task.task_id,
        "baseline_summary": baseline_summary,
        "reuse_applications": reuse_applications,
        "summary": summary,
        "verification": verification.__dict__,
        "contradiction_gain": contradiction_gain,
    }


def _run_ablation_eval(
    task: HeldoutTaskSpec, *, config: DENSNConfig, prefix: str
) -> dict[str, Any]:
    registry = OntologyRegistry()
    system = DENSNSystem(_graph_builder(task, prefix), config, registry=registry)
    summary = system.run_until_stable()
    return {**summary, "registry_lifecycle_summary": registry.lifecycle_summary()}


def _run_live_model_baseline(target_task: HeldoutTaskSpec) -> dict[str, Any]:
    source_manifest = load_json(train_manifest_path())
    target_manifest = load_json(Path(str(target_task.inputs["manifest_path"])))
    baseline_system = DENSNSystem(
        _graph_builder(target_task, "model_baseline"),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    _register_verifier(baseline_system)
    baseline_summary = baseline_system.run_until_stable()
    try:
        hypothesis = request_groq_json(
            model_baseline_prompt(source_manifest, target_manifest, with_retrieval=True)
        )
        verification = baseline_system.verifier.verify(
            VerificationClaim(
                kind=CLAIM_KIND,
                payload={
                    "task_id": target_task.task_id,
                    "manifest_path": str(target_task.inputs["manifest_path"]),
                    "parent_roles": list(hypothesis.get("canonical_parent_roles", [])),
                    "blanket_roles": list(hypothesis.get("canonical_blanket_roles", [])),
                },
            )
        )
        return {
            "status": "completed",
            "hypothesis": hypothesis,
            "summary": baseline_summary,
            "verification": verification.__dict__,
            "contradiction_gain": 0.0,
        }
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": str(exc),
            "summary": baseline_summary,
        }


def _interface_is_constant(record: dict[str, Any] | None) -> bool | None:
    if record is None:
        return None
    truth_table = record.get("interface_definition", {}).get("truth_table", {})
    values = set(bool(value) for value in truth_table.values())
    if not values:
        return None
    return len(values) == 1


def run_credit_window_benchmark(output_dir: str = "artifacts/phase12") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase12", root=ROOT)

    registry = OntologyRegistry()
    tasks = heldout_specs()

    train_graph = build_credit_window_graph_from_manifest(
        train_manifest_path(), prefix="TRAIN_CREDIT"
    )
    train_system = DENSNSystem(train_graph, credit_window_config(), registry=registry)
    _register_verifier(train_system)
    train_system.register_candidate_evaluator(
        VerifierBackedReuseEvaluator(
            heldout_tasks=tasks,
            graph_builder=_graph_builder,
            verifier_registrar=_register_verifier,
            training_claim_builder=_training_claim,
            heldout_claim_builder=_heldout_claim,
            baseline_config=no_tsl_config(),
            reuse_config=reuse_only_config(),
        )
    )
    train_summary = train_system.run_until_stable()

    meta_id, record = _accepted_meta_record(registry)
    transfer_results: list[dict[str, Any]] = []
    negative_transfer = None
    baseline_no_tsl = None
    baseline_no_conflict = None
    live_model_baseline = None

    if meta_id is not None and record is not None:
        for task in tasks:
            transfer_results.append(_run_transfer_eval(registry, task))
        negative_transfer = _run_transfer_eval(registry, negative_transfer_spec())
        baseline_no_tsl = _run_ablation_eval(
            tasks[0], config=no_tsl_config(), prefix="BASELINE_CREDIT_NO_TSL"
        )
        baseline_no_conflict = _run_ablation_eval(
            tasks[0],
            config=no_conflict_memory_config(),
            prefix="BASELINE_CREDIT_NO_CONFLICT",
        )
        live_model_baseline = _run_live_model_baseline(tasks[0])

    train_graph_path = target_dir / "credit_window_train_graph.json"
    train_graph.save(str(train_graph_path))
    train_telemetry_path = target_dir / "credit_window_train_telemetry.jsonl"
    train_system.telemetry.flush(str(train_telemetry_path))
    registry_path = target_dir / "credit_window_registry.json"
    registry.save(str(registry_path))

    lifecycle_summary = registry.lifecycle_summary()
    accepted_metrics = None if record is None else record.get("admission_metrics", {})
    negative_verifier = (
        {} if negative_transfer is None else negative_transfer.get("verification", {})
    )
    live_baseline_beaten = None
    if live_model_baseline and live_model_baseline.get("status") == "completed":
        live_baseline_beaten = bool(
            transfer_results
            and transfer_results[0].get("verification", {}).get("passed")
            and float(transfer_results[0].get("summary", {}).get("final_psi") or 0.0) <= 0.0
            and (
                not live_model_baseline.get("verification", {}).get("passed")
                or float(live_model_baseline.get("contradiction_gain") or 0.0) <= 0.0
            )
        )

    summary = {
        "domain": "credit_window",
        "artifact_version": version,
        "proof_contract": {
            **train_system.core_contract(),
            "runtime_metrics": train_summary.get("runtime_metrics", {}),
            "lifecycle_metrics": lifecycle_summary,
            "transfer_metrics": transfer_metrics_summary(transfer_results=transfer_results),
        },
        "train_manifest_path": str(train_manifest_path()),
        "train_summary": train_summary,
        "accepted_meta_symbol_id": meta_id,
        "accepted_record": record,
        "accepted_admission_metrics": accepted_metrics,
        "accepted_interface_is_constant": _interface_is_constant(record),
        "transfer_results": transfer_results,
        "negative_transfer": negative_transfer,
        "live_model_baseline": live_model_baseline,
        "baseline_no_tsl": baseline_no_tsl,
        "baseline_no_conflict_memory": baseline_no_conflict,
        "artifact_files": {
            "credit_window_train_graph": str(train_graph_path.resolve()),
            "credit_window_train_telemetry": str(train_telemetry_path.resolve()),
            "credit_window_registry": str(registry_path.resolve()),
        },
        "checks": {
            "accepted_symbol": meta_id is not None,
            "accepted_interface_non_constant": _interface_is_constant(record) is False,
            "heldout_reuse_success": bool(
                transfer_results
                and all(result.get("verification", {}).get("passed") for result in transfer_results)
                and all(
                    float(
                        result.get("summary", {}).get("final_psi")
                        if result.get("summary", {}).get("final_psi") is not None
                        else 1.0
                    )
                    <= 0.0
                    for result in transfer_results
                )
            ),
            "negative_transfer_blocked": negative_verifier.get("passed") is False,
            "live_model_baseline_beaten": live_baseline_beaten,
        },
    }

    transfer_summary = {
        "artifact_version": version,
        "source_family": "credit_window",
        "positive_transfer_count": len(transfer_results),
        "positive_transfer_targets": [result.get("task_id") for result in transfer_results],
        "transfer_results": transfer_results,
        "negative_transfer": negative_transfer,
        "live_model_baseline": live_model_baseline,
        "baseline_superiority": {
            "densn_contradiction_gain": None
            if not transfer_results
            else transfer_results[0].get("contradiction_gain"),
            "live_model_baseline_beaten": live_baseline_beaten,
        },
    }

    write_json_artifact(target_dir / "credit_window_summary.json", summary, version=version)
    write_json_artifact(
        target_dir / "credit_window_transfer_summary.json", transfer_summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase12_credit_window_report.md",
        "\n".join(
            [
                "# Phase 12 Credit Window",
                "",
                f"- accepted_symbol: `{summary['checks']['accepted_symbol']}`",
                f"- accepted_interface_non_constant: `{summary['checks']['accepted_interface_non_constant']}`",
                f"- heldout_reuse_success: `{summary['checks']['heldout_reuse_success']}`",
                f"- negative_transfer_blocked: `{summary['checks']['negative_transfer_blocked']}`",
                f"- live_model_baseline_beaten: `{summary['checks']['live_model_baseline_beaten']}`",
            ]
        )
        + "\n",
        version=version,
    )
    return summary
