"""Artifact-backed Pathway A compression benchmark."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from ..artifacts import attach_artifact_manifest, link_provenance
from ..graph import PersistentGraph
from ..lifecycle import HeldoutTaskSpec
from ..memory import OntologyRegistry
from ..records import AtomicSymbol, Constraint, Edge, VerificationClaim
from ..system import DENSNConfig, DENSNSystem

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "fixtures" / "session_macro"
VERIFIER_SCRIPT = ROOT / "verifiers" / "session_macro_verifier.py"
CLAIM_KIND = "session_macro_compression"


def train_manifest_path() -> Path:
    return FIXTURES_DIR / "train" / "manifest.json"


def heldout_specs() -> list[HeldoutTaskSpec]:
    return [
        HeldoutTaskSpec(
            task_id="session_macro_heldout_a",
            family="session_macro",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_macro_a" / "manifest.json")},
        ),
        HeldoutTaskSpec(
            task_id="session_macro_heldout_b",
            family="session_macro",
            split="heldout",
            inputs={"manifest_path": str(FIXTURES_DIR / "heldout_macro_b" / "manifest.json")},
        ),
    ]


def build_session_macro_graph_from_manifest(
    manifest_path: str | Path,
    prefix: str | None = None,
) -> PersistentGraph:
    graph = PersistentGraph()
    artifact_info = attach_artifact_manifest(graph, manifest_path)
    manifest = artifact_info["manifest"]
    evidence_ids = artifact_info["evidence_ids"]

    prefix = prefix or manifest["task_id"].upper()
    module_count = int(manifest.get("module_count", 1))
    roles = manifest.get("roles", {})
    start_token = str(roles.get("start", "START"))
    update_token = str(roles.get("update", "UPDATE"))
    finish_token = str(roles.get("finish", "FINISH"))

    all_symbols: list[str] = []
    all_constraints: list[str] = []
    for index in range(1, module_count + 1):
        start_symbol = AtomicSymbol(
            id=f"{prefix}_START_{index}",
            name=f"{start_token}_{index}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "start",
                "canonical_role": "open",
                "module_index": index,
                "task_id": manifest["task_id"],
            },
        )
        update_symbol = AtomicSymbol(
            id=f"{prefix}_UPDATE_{index}",
            name=f"{update_token}_{index}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "update",
                "canonical_role": "write",
                "module_index": index,
                "task_id": manifest["task_id"],
            },
        )
        finish_symbol = AtomicSymbol(
            id=f"{prefix}_FINISH_{index}",
            name=f"{finish_token}_{index}",
            truth_value=True,
            locked=True,
            provenance_ids=list(evidence_ids.values()),
            metadata={
                "role": "finish",
                "canonical_role": "close",
                "module_index": index,
                "task_id": manifest["task_id"],
            },
        )
        for symbol in (start_symbol, update_symbol, finish_symbol):
            graph.add_node(symbol)
            all_symbols.append(symbol.id)

        constraints = [
            Constraint(
                id=f"{prefix}_C_START_UPDATE_{index}",
                constraint_kind="implies",
                symbol_ids=[start_symbol.id, update_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("execution_traces", ""),
                ],
                metadata={"module_index": index, "rule": "start_implies_update"},
            ),
            Constraint(
                id=f"{prefix}_C_START_FINISH_{index}",
                constraint_kind="implies",
                symbol_ids=[start_symbol.id, finish_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[
                    evidence_ids.get("formal_spec", ""),
                    evidence_ids.get("failing_tests", ""),
                ],
                metadata={"module_index": index, "rule": "start_implies_finish"},
            ),
            Constraint(
                id=f"{prefix}_C_UPDATE_FINISH_{index}",
                constraint_kind="implies",
                symbol_ids=[update_symbol.id, finish_symbol.id],
                base_weight=1.0,
                weight=1.0,
                max_weight=16.0,
                provenance_ids=[evidence_ids.get("formal_spec", ""), evidence_ids.get("logs", "")],
                metadata={"module_index": index, "rule": "update_implies_finish"},
            ),
        ]
        for constraint in constraints:
            graph.add_node(constraint)
            all_constraints.append(constraint.id)
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
        for key in ("natural_language_spec", "formal_spec", "source_code_path")
        if key in evidence_ids
    ]
    constraint_evidence = [
        evidence_ids[key]
        for key in ("formal_spec", "execution_traces", "failing_tests", "counterexamples")
        if key in evidence_ids
    ]
    link_provenance(graph, symbol_evidence, all_symbols)
    link_provenance(graph, constraint_evidence, all_constraints)
    return graph


def pathway_a_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=1.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=2,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=4,
        random_seed=7,
        require_verifier_for_admission=True,
        require_reuse_for_admission=True,
        min_heldout_contradiction_gain=0.0,
        max_complexity_penalty=8.0,
    )


def reuse_only_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=-1.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=2,
        random_seed=7,
    )


def no_pathway_a_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=-1.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=2,
        random_seed=7,
    )


def _register_verifier(system: DENSNSystem) -> None:
    system.verifier.register_subprocess(
        CLAIM_KIND,
        [sys.executable, str(VERIFIER_SCRIPT)],
        cwd=str(ROOT),
        timeout_seconds=30.0,
    )


def _macro_claim(
    system: DENSNSystem,
    meta_symbol,
    manifest_path: str | Path,
) -> VerificationClaim:
    return VerificationClaim(
        kind=CLAIM_KIND,
        payload={
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
        },
    )


def _first_accepted_meta_symbol_id(registry: OntologyRegistry) -> str | None:
    for meta_symbol_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_symbol_id
    return None


def _active_constraint_count(graph: PersistentGraph) -> int:
    return len(list(graph.iter_constraints(active_only=True)))


def _run_fixed_cycles(system: DENSNSystem, max_cycles: int) -> dict[str, Any]:
    last_result: dict[str, Any] = {}
    for cycle_index in range(max_cycles):
        last_result = system.run_cycle(cycle_index)
    return {
        "cycles_run": max_cycles,
        "final_psi": last_result.get("psi_after"),
        "registry": system.registry.summary(),
        "telemetry_summary": system.telemetry.summary(),
        "runtime_metrics": system.runtime_metrics(),
        "active_constraint_count": _active_constraint_count(system.graph),
        "node_count": len(system.graph.nodes),
        "pathway_a_event_count": sum(
            1
            for event in system.telemetry.events
            if event.get("event_type") == "tsl_event" and event.get("pathway") == "A"
        ),
    }


class PathwayAFreshAdmissionEvaluator:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = str(manifest_path)

    def __call__(self, system: DENSNSystem, context: dict[str, Any]) -> dict[str, Any]:
        if context.get("pathway") != "A":
            return {
                "verifier_passed": False,
                "reuse_passed": False,
                "heldout_contradiction_gain": 0.0,
                "rent_paid": False,
            }
        proposal = context["proposal"]
        revision = context["revision"]
        verification = system.verifier.verify(
            _macro_claim(system, proposal.meta_symbol, self.manifest_path)
        )
        compression_gain = float(len(revision.retired_constraint_ids))
        return {
            "verification_results": [verification],
            "verifier_passed": verification.passed,
            "reuse_passed": True,
            "heldout_contradiction_gain": compression_gain,
            "complexity_penalty": float(
                len(revision.cluster_symbol_ids) + len(revision.retired_constraint_ids)
            ),
            "rent_paid": verification.passed and compression_gain > 0.0,
        }


class PathwayACompressionEvaluator:
    def __init__(self, heldout_tasks: list[HeldoutTaskSpec]) -> None:
        self.heldout_tasks = list(heldout_tasks)

    def __call__(self, system: DENSNSystem, context: dict[str, Any]) -> dict[str, Any]:
        if context.get("pathway") != "A":
            return {
                "verifier_passed": False,
                "reuse_passed": False,
                "heldout_contradiction_gain": 0.0,
                "rent_paid": False,
            }

        proposal = context["proposal"]
        revision = context["revision"]
        train_verification = system.verifier.verify(
            _macro_claim(system, proposal.meta_symbol, train_manifest_path())
        )

        source_active_after = _active_constraint_count(system.graph)
        source_active_before = source_active_after + len(revision.retired_constraint_ids)
        source_nodes_after = len(system.graph.nodes)
        source_nodes_before = source_nodes_after - 1

        heldout_results: list[dict[str, Any]] = []
        reuse_records: list[dict[str, Any]] = []
        cycle_reductions: list[float] = []
        verifier_call_reductions: list[float] = []
        cache_active_reductions: list[float] = []
        no_pathway_a_reductions: list[float] = []
        reuse_count = 0
        reuse_passed = True

        for task in self.heldout_tasks:
            manifest_path = str(task.inputs["manifest_path"])

            fresh_registry = OntologyRegistry()
            fresh_system = DENSNSystem(
                build_session_macro_graph_from_manifest(
                    manifest_path, prefix=f"{task.task_id.upper()}_FRESH"
                ),
                pathway_a_config(),
                registry=fresh_registry,
            )
            _register_verifier(fresh_system)
            fresh_system.register_candidate_evaluator(
                PathwayAFreshAdmissionEvaluator(manifest_path)
            )
            fresh_summary = _run_fixed_cycles(fresh_system, max_cycles=2)

            fresh_meta_id = _first_accepted_meta_symbol_id(fresh_registry)
            fresh_verification_passed = fresh_meta_id is not None
            if fresh_meta_id is not None:
                fresh_verification = fresh_system.verifier.verify(
                    _macro_claim(
                        fresh_system, fresh_system.graph.get_node(fresh_meta_id), manifest_path
                    )
                )
                fresh_verification_passed = fresh_verification.passed

            reuse_system = DENSNSystem(
                build_session_macro_graph_from_manifest(
                    manifest_path, prefix=f"{task.task_id.upper()}_REUSE"
                ),
                reuse_only_config(),
                registry=system.registry,
            )
            _register_verifier(reuse_system)
            reuse_application = reuse_system.apply_registry_symbol(
                proposal.meta_symbol.id,
                task_id=task.task_id,
                graph=reuse_system.graph,
            )
            reuse_summary = _run_fixed_cycles(reuse_system, max_cycles=1)
            reuse_verification_passed = False
            if reuse_application.get("applied"):
                reuse_count += 1
                reuse_verification = reuse_system.verifier.verify(
                    _macro_claim(
                        reuse_system,
                        reuse_system.graph.get_node(
                            str(reuse_application["instantiated_meta_symbol_id"])
                        ),
                        manifest_path,
                    )
                )
                reuse_verification_passed = reuse_verification.passed

            cache_only_system = DENSNSystem(
                build_session_macro_graph_from_manifest(
                    manifest_path, prefix=f"{task.task_id.upper()}_CACHE"
                ),
                reuse_only_config(),
                registry=system.registry,
            )
            _register_verifier(cache_only_system)
            cache_only_summary = _run_fixed_cycles(cache_only_system, max_cycles=1)

            no_pathway_a_system = DENSNSystem(
                build_session_macro_graph_from_manifest(
                    manifest_path, prefix=f"{task.task_id.upper()}_NO_PA"
                ),
                no_pathway_a_config(),
                registry=OntologyRegistry(),
            )
            _register_verifier(no_pathway_a_system)
            no_pathway_a_summary = _run_fixed_cycles(no_pathway_a_system, max_cycles=1)

            fresh_cycles = int(fresh_summary["cycles_run"])
            reuse_cycles = int(reuse_summary["cycles_run"])
            fresh_verifier_calls = int(
                fresh_summary.get("runtime_metrics", {}).get("verifier_calls_to_acceptance") or 0
            )
            reuse_verifier_calls = int(
                reuse_summary.get("runtime_metrics", {}).get("verifier_calls_to_acceptance") or 0
            )
            cache_active = int(cache_only_summary["active_constraint_count"])
            reuse_active = int(reuse_summary["active_constraint_count"])
            no_pathway_a_active = int(no_pathway_a_summary["active_constraint_count"])

            cycle_reduction = float(fresh_cycles - reuse_cycles)
            verifier_call_reduction = float(fresh_verifier_calls - reuse_verifier_calls)
            cache_active_reduction = float(cache_active - reuse_active)
            no_pathway_a_reduction = float(no_pathway_a_active - reuse_active)
            reuse_success = (
                bool(reuse_application.get("applied"))
                and reuse_verification_passed
                and cycle_reduction > 0.0
                and cache_active_reduction > 0.0
                and no_pathway_a_reduction > 0.0
            )

            cycle_reductions.append(cycle_reduction)
            verifier_call_reductions.append(verifier_call_reduction)
            cache_active_reductions.append(cache_active_reduction)
            no_pathway_a_reductions.append(no_pathway_a_reduction)
            reuse_passed = reuse_passed and reuse_success

            heldout_results.append(
                {
                    "task_id": task.task_id,
                    "fresh_pathway_a_cycles": fresh_cycles,
                    "reuse_cycles": reuse_cycles,
                    "cycle_reduction": cycle_reduction,
                    "fresh_verifier_calls": fresh_verifier_calls,
                    "reuse_verifier_calls": reuse_verifier_calls,
                    "verifier_call_reduction": verifier_call_reduction,
                    "reuse_applied": reuse_application.get("applied", False),
                    "reuse_verification_passed": reuse_verification_passed,
                    "fresh_verification_passed": fresh_verification_passed,
                    "cache_only_active_constraints": cache_active,
                    "reuse_active_constraints": reuse_active,
                    "no_pathway_a_active_constraints": no_pathway_a_active,
                    "cache_only_active_constraint_reduction": cache_active_reduction,
                    "no_pathway_a_active_constraint_reduction": no_pathway_a_reduction,
                }
            )
            reuse_records.append(
                {
                    "task_id": task.task_id,
                    "outcome": {
                        "reuse_passed": reuse_success,
                        "verifier_passed": reuse_verification_passed,
                        "reuse_applied": reuse_application.get("applied", False),
                        "cycle_reduction": cycle_reduction,
                        "verifier_call_reduction": verifier_call_reduction,
                    },
                }
            )

        average_cycle_reduction = sum(cycle_reductions) / max(len(cycle_reductions), 1)
        average_verifier_call_reduction = sum(verifier_call_reductions) / max(
            len(verifier_call_reductions), 1
        )
        average_cache_reduction = sum(cache_active_reductions) / max(
            len(cache_active_reductions), 1
        )
        average_no_pathway_a_reduction = sum(no_pathway_a_reductions) / max(
            len(no_pathway_a_reductions), 1
        )

        return {
            "verification_results": [train_verification],
            "reuse_records": reuse_records,
            "verifier_passed": train_verification.passed,
            "reuse_passed": reuse_passed,
            "heldout_contradiction_gain": average_cycle_reduction,
            "complexity_penalty": float(
                len(revision.cluster_symbol_ids) + len(revision.retired_constraint_ids)
            ),
            "rent_paid": train_verification.passed
            and reuse_passed
            and average_cycle_reduction > 0.0
            and average_cache_reduction > 0.0
            and average_no_pathway_a_reduction > 0.0,
            "compression_gain": float(len(revision.retired_constraint_ids)),
            "mdl_or_symbolic_tax_reduction": float(source_active_before - source_active_after),
            "ontology_size_before_after": {
                "node_count_before": source_nodes_before,
                "node_count_after": source_nodes_after,
                "active_constraints_before": source_active_before,
                "active_constraints_after": source_active_after,
            },
            "downstream_cycles_reduction": average_cycle_reduction,
            "downstream_verifier_calls_reduction": average_verifier_call_reduction,
            "reuse_of_compressed_structure_count": reuse_count,
            "pathway_a_vs_cache_only_ablation": {
                "average_active_constraint_reduction": average_cache_reduction,
            },
            "pathway_a_vs_no_pathway_a_ablation": {
                "average_active_constraint_reduction": average_no_pathway_a_reduction,
                "average_cycle_reduction": average_cycle_reduction,
            },
            "heldout_results": heldout_results,
        }


def run_pathway_a_benchmark(output_dir: str = "artifacts/phase8") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase8", root=ROOT)

    registry = OntologyRegistry()
    graph = build_session_macro_graph_from_manifest(
        train_manifest_path(), prefix="SESSION_MACRO_TRAIN"
    )
    system = DENSNSystem(graph, pathway_a_config(), registry=registry)
    _register_verifier(system)
    system.register_candidate_evaluator(PathwayACompressionEvaluator(heldout_specs()))
    train_summary = _run_fixed_cycles(system, max_cycles=2)

    accepted_meta_symbol_id = _first_accepted_meta_symbol_id(registry)
    accepted_record = (
        None if accepted_meta_symbol_id is None else dict(registry.records[accepted_meta_symbol_id])
    )
    accepted_metrics = (
        {} if accepted_record is None else dict(accepted_record.get("admission_metrics", {}))
    )

    summary = {
        "domain": "pathway_a_session_macro",
        "artifact_version": version,
        "proof_contract": {
            **system.core_contract(),
            "runtime_metrics": train_summary.get("runtime_metrics", {}),
            "lifecycle_metrics": registry.lifecycle_summary(),
        },
        "train_manifest_path": str(train_manifest_path()),
        "train_summary": train_summary,
        "accepted_meta_symbol_id": accepted_meta_symbol_id,
        "accepted_record": accepted_record,
        "accepted_admission_metrics": accepted_metrics,
        "compression_gain": accepted_metrics.get("compression_gain"),
        "mdl_or_symbolic_tax_reduction": accepted_metrics.get("mdl_or_symbolic_tax_reduction"),
        "ontology_size_before_after": accepted_metrics.get("ontology_size_before_after"),
        "downstream_cycles_reduction": accepted_metrics.get("downstream_cycles_reduction"),
        "downstream_verifier_calls_reduction": accepted_metrics.get(
            "downstream_verifier_calls_reduction"
        ),
        "reuse_of_compressed_structure_count": accepted_metrics.get(
            "reuse_of_compressed_structure_count"
        ),
        "pathway_a_vs_cache_only_ablation": accepted_metrics.get(
            "pathway_a_vs_cache_only_ablation"
        ),
        "pathway_a_vs_no_pathway_a_ablation": accepted_metrics.get(
            "pathway_a_vs_no_pathway_a_ablation"
        ),
        "heldout_results": accepted_metrics.get("heldout_results", []),
        "checks": {
            "accepted_pathway_a_symbol": accepted_meta_symbol_id is not None,
            "compression_gain_positive": float(accepted_metrics.get("compression_gain", 0.0) or 0.0)
            > 0.0,
            "downstream_cycles_reduction_positive": float(
                accepted_metrics.get("downstream_cycles_reduction", 0.0) or 0.0
            )
            > 0.0,
            "downstream_verifier_calls_reduction_positive": float(
                accepted_metrics.get("downstream_verifier_calls_reduction", 0.0) or 0.0
            )
            > 0.0,
            "cache_only_ablation_positive": float(
                accepted_metrics.get("pathway_a_vs_cache_only_ablation", {}).get(
                    "average_active_constraint_reduction", 0.0
                )
                or 0.0
            )
            > 0.0,
            "no_pathway_a_ablation_positive": float(
                accepted_metrics.get("pathway_a_vs_no_pathway_a_ablation", {}).get(
                    "average_cycle_reduction", 0.0
                )
                or 0.0
            )
            > 0.0,
        },
    }
    write_json_artifact(target_dir / "pathway_a_summary.json", summary, version=version)
    write_text_artifact(
        ROOT / "reports" / "phase8_pathway_a_report.md",
        "\n".join(
            [
                "# Phase 8 Pathway A",
                "",
                f"- accepted_pathway_a_symbol: `{summary['checks']['accepted_pathway_a_symbol']}`",
                f"- compression_gain: `{summary['compression_gain']}`",
                f"- downstream_cycles_reduction: `{summary['downstream_cycles_reduction']}`",
                f"- downstream_verifier_calls_reduction: `{summary['downstream_verifier_calls_reduction']}`",
            ]
        )
        + "\n",
        version=version,
    )
    return summary
