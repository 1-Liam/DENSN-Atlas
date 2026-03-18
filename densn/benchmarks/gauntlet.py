"""Unified phase-7 gauntlet benchmark."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from ..memory import OntologyRegistry
from ..proof_contract import CORE_API_VERSION, transfer_metrics_summary
from ..proposal_review import ArtifactStructuralProposalReviewer
from ..system import DENSNSystem
from ..transformer import ArtifactHeuristicTransformerAdapter
from .formal_protocol import run_formal_protocol_benchmark
from .gauntlet_support import (
    build_commit_family_graph_from_manifest,
    build_window_family_graph_from_manifest,
    claim_for_meta_symbol,
    claim_without_application,
    integrate_secondary_verifier_evidence,
    load_json,
    model_baseline_prompt,
    register_secondary_verifiers,
    request_groq_json,
    reuse_only_config,
    row,
    runtime_row_fields,
)
from .proposal_runtime import _build_train_system, run_proposal_runtime_benchmark
from .quorum_commit import run_quorum_commit_benchmark
from .remap_transfer import (
    LEASE_CLAIM_KIND,
    LEASE_VERIFIER_SCRIPT,
    VOTE_CLAIM_KIND,
    VOTE_VERIFIER_SCRIPT,
    build_lease_lock_graph_from_manifest,
)
from .transfer_matrix import run_transfer_matrix_benchmark

ROOT = Path(__file__).resolve().parents[2]
SESSION_FIXTURES_DIR = ROOT / "fixtures" / "session_epoch"
LEASE_FIXTURES_DIR = ROOT / "fixtures" / "lease_lock"
REPLICATION_FIXTURES_DIR = ROOT / "fixtures" / "replication_barrier"
QUORUM_FIXTURES_DIR = ROOT / "fixtures" / "quorum_commit"
VOTE_FIXTURES_DIR = ROOT / "fixtures" / "vote_majority_commit"
SESSION_VERIFIER_SCRIPT = ROOT / "verifiers" / "session_epoch_verifier.py"
REPLICATION_VERIFIER_SCRIPT = ROOT / "verifiers" / "replication_barrier_verifier.py"
SESSION_CLAIM_KIND = "session_epoch_invariant"
REPLICATION_CLAIM_KIND = "replication_barrier_invariant"


def _source_paths() -> dict[str, Path]:
    return {
        "protocol_summary": ROOT / "artifacts" / "phase1" / "formal_summary.json",
        "protocol_registry": ROOT / "artifacts" / "phase1" / "formal_registry.json",
        "quorum_summary": ROOT / "artifacts" / "phase3" / "quorum_summary.json",
        "quorum_registry": ROOT / "artifacts" / "phase3" / "quorum_registry.json",
        "protocol_runtime": ROOT / "artifacts" / "phase2" / "proposal_runtime_summary.json",
        "quorum_runtime": ROOT / "artifacts" / "phase4" / "quorum_proposal_runtime_summary.json",
    }


def _first_accepted_record(registry: OntologyRegistry) -> tuple[str, dict[str, Any]]:
    for meta_symbol_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_symbol_id, record
    raise RuntimeError("Expected an accepted meta-symbol in the registry.")


def _proposal_runtime_metrics(path: Path) -> dict[str, Any]:
    raw = load_json(path)
    proposal_assisted = raw.get("proposal_assisted", {}).get("summary", {})
    return {
        **runtime_row_fields(proposal_assisted),
        "proposal_adapter": raw.get("proposal_assisted", {}).get("adapter"),
    }


def _summary_row(
    *,
    system_name: str,
    family: str,
    summary: dict[str, Any],
    artifact_version: dict[str, Any],
    case_kind: str,
    mapping_class: str | None,
    verifier_stack: list[dict[str, Any]] | None = None,
    proposal_adapter: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return row(
        system_name=system_name,
        family=family,
        target_family=family,
        case_kind=case_kind,
        mapping_class=mapping_class,
        baseline_final_psi=float(summary.get("final_psi") or 0.0),
        transfer_final_psi=float(summary.get("final_psi") or 0.0),
        contradiction_gain=0.0,
        verifier_results=[],
        verifier_stack=list(verifier_stack or []),
        source_runtime_metrics=runtime_row_fields(summary),
        accepted_interface_is_constant=None,
        proposal_adapter=proposal_adapter,
        artifact_version=artifact_version,
        extra=extra,
    )


def _interface_is_constant(record: dict[str, Any]) -> bool | None:
    truth_table = record.get("interface_definition", {}).get("truth_table", {})
    if not truth_table:
        return None
    return len({bool(value) for value in truth_table.values()}) == 1


def _run_densn_transfer_case(
    *,
    source_family: str,
    source_runtime_metrics: dict[str, Any],
    source_record: dict[str, Any],
    registry: OntologyRegistry,
    manifest_path: Path,
    graph_builder,
    claim_kind: str,
    subprocess_command: list[str],
    artifact_version: dict[str, Any],
    case_kind: str = "positive_transfer",
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    baseline_system = DENSNSystem(
        graph_builder(manifest_path, prefix=f"{manifest['task_id'].upper()}_BASELINE"),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        graph_builder(manifest_path, prefix=f"{manifest['task_id'].upper()}_REUSE"),
        reuse_only_config(),
        registry=registry,
    )
    register_secondary_verifiers(
        reuse_system, claim_kind=claim_kind, subprocess_command=subprocess_command, cwd=str(ROOT)
    )
    reuse_applications = reuse_system.apply_reusable_symbols(
        task_id=manifest["task_id"], graph=reuse_system.graph
    )
    reuse_summary = reuse_system.run_until_stable()

    verifier_results = []
    mapping_class = None
    mapping_confidence = None
    if reuse_applications:
        application = reuse_applications[0]
        mapping_class = application.get("mapping_class")
        mapping_confidence = application.get("mapping_confidence")
        claim = claim_for_meta_symbol(
            reuse_system,
            meta_symbol_id=str(application["instantiated_meta_symbol_id"]),
            manifest_path=manifest_path,
            claim_kind=claim_kind,
            record=source_record,
        )
        verifier_results = reuse_system.verifier.verify_all(claim)
        integrate_secondary_verifier_evidence(
            reuse_system,
            node_id=str(application["instantiated_meta_symbol_id"]),
            results=verifier_results,
        )

    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        reuse_summary.get("final_psi") or 0.0
    )
    return row(
        system_name="densn_live",
        family=source_family,
        target_family=manifest["family"],
        case_kind=case_kind,
        mapping_class=mapping_class,
        baseline_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        transfer_final_psi=float(reuse_summary.get("final_psi") or 0.0),
        contradiction_gain=contradiction_gain,
        verifier_results=verifier_results,
        verifier_stack=reuse_system.verifier.describe(),
        source_runtime_metrics=source_runtime_metrics,
        accepted_interface_is_constant=_interface_is_constant(source_record),
        proposal_adapter=source_runtime_metrics.get("proposal_adapter"),
        artifact_version=artifact_version,
        extra={
            "reuse_application_count": len(reuse_applications),
            "mapping_confidence": mapping_confidence,
            "positive_transfer": bool(
                verifier_results and verifier_results[0].passed and contradiction_gain > 0.0
            ),
            "cycles_to_useful_outcome": source_runtime_metrics.get(
                "cycles_to_first_accepted_symbol"
            ),
            "useful_outcome_kind": "positive_transfer",
        },
    )


def _run_invalid_cross_ladder_case(
    *,
    source_family: str,
    source_runtime_metrics: dict[str, Any],
    source_record: dict[str, Any],
    manifest_path: Path,
    graph_builder,
    claim_kind: str,
    subprocess_command: list[str],
    artifact_version: dict[str, Any],
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    target_system = DENSNSystem(
        graph_builder(manifest_path, prefix=f"{manifest['task_id'].upper()}_CROSS"),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    register_secondary_verifiers(
        target_system, claim_kind=claim_kind, subprocess_command=subprocess_command, cwd=str(ROOT)
    )
    baseline_summary = target_system.run_until_stable()
    verifier_results = target_system.verifier.verify_all(
        claim_without_application(
            manifest_path=manifest_path, claim_kind=claim_kind, record=source_record
        )
    )
    return row(
        system_name="densn_live",
        family=source_family,
        target_family=manifest["family"],
        case_kind="cross_ladder_invalid",
        mapping_class="invalid_transfer",
        baseline_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        transfer_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        contradiction_gain=0.0,
        verifier_results=verifier_results,
        verifier_stack=target_system.verifier.describe(),
        source_runtime_metrics=source_runtime_metrics,
        accepted_interface_is_constant=_interface_is_constant(source_record),
        proposal_adapter=source_runtime_metrics.get("proposal_adapter"),
        artifact_version=artifact_version,
        extra={"reuse_application_count": 0, "mapping_confidence": 0.0, "positive_transfer": False},
    )


def _evaluate_model_baseline_row(
    *,
    system_name: str,
    source_family: str,
    source_manifest_path: Path,
    target_manifest_path: Path,
    target_graph_builder,
    claim_kind: str,
    subprocess_command: list[str],
    artifact_version: dict[str, Any],
    with_retrieval: bool,
) -> dict[str, Any]:
    source_manifest = load_json(source_manifest_path)
    target_manifest = load_json(target_manifest_path)
    baseline_system = DENSNSystem(
        target_graph_builder(
            target_manifest_path,
            prefix=f"{target_manifest['task_id'].upper()}_{system_name.upper()}",
        ),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    register_secondary_verifiers(
        baseline_system, claim_kind=claim_kind, subprocess_command=subprocess_command, cwd=str(ROOT)
    )
    baseline_summary = baseline_system.run_until_stable()

    hypothesis = request_groq_json(
        model_baseline_prompt(source_manifest, target_manifest, with_retrieval=with_retrieval)
    )
    parent_roles = list(hypothesis.get("canonical_parent_roles", []))
    blanket_roles = list(hypothesis.get("canonical_blanket_roles", []))
    verifier_results = []
    if parent_roles and blanket_roles:
        verifier_results = baseline_system.verifier.verify_all(
            claim_without_application(
                manifest_path=target_manifest_path,
                claim_kind=claim_kind,
                record={
                    "reuse_signature": {
                        "parent_roles": parent_roles,
                        "blanket_roles": blanket_roles,
                        "canonical_parent_roles": parent_roles,
                        "canonical_blanket_roles": blanket_roles,
                    }
                },
            )
        )
    positive_transfer = bool(
        verifier_results
        and verifier_results[0].passed
        and float(baseline_summary.get("final_psi") or 0.0) <= 0.0
    )
    return row(
        system_name=system_name,
        family=source_family,
        target_family=target_manifest["family"],
        case_kind="baseline_transfer",
        mapping_class="retrieval_guided_hypothesis"
        if with_retrieval
        else "direct_model_hypothesis",
        baseline_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        transfer_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        contradiction_gain=0.0,
        verifier_results=verifier_results,
        verifier_stack=baseline_system.verifier.describe(),
        source_runtime_metrics={
            "cycles_to_first_accepted_symbol": None,
            "verifier_calls_to_acceptance": len(verifier_results),
            "rollback_count": 0,
            "retirement_count": 0,
            "false_candidate_count": 0,
            "contradiction_before_acceptance": None,
        },
        accepted_interface_is_constant=None,
        proposal_adapter="GroqChatTransformerAdapter",
        artifact_version=artifact_version,
        extra={
            "hypothesis": hypothesis,
            "positive_transfer": positive_transfer,
            "cycles_to_useful_outcome": baseline_summary.get("cycles_run"),
            "useful_outcome_kind": (
                "positive_transfer" if positive_transfer else "budget_exhausted_without_transfer"
            ),
        },
    )


def _heuristic_runtime_row(family: str, artifact_version: dict[str, Any]) -> dict[str, Any]:
    adapter = ArtifactHeuristicTransformerAdapter()
    reviewer = ArtifactStructuralProposalReviewer()
    baseline_registry = OntologyRegistry()
    baseline_system, _ = _build_train_system(baseline_registry, with_proposals=False, family=family)
    proposal_registry = OntologyRegistry()
    proposal_system, _ = _build_train_system(proposal_registry, with_proposals=False, family=family)
    proposal_system.set_transformer_adapter(adapter)
    proposal_system.register_proposal_reviewer(reviewer)
    if family == "protocol_guard":
        manifest_path = str(
            (ROOT / "fixtures" / "protocol_guard" / "train" / "manifest.json").resolve()
        )
        evidence_query = "guard protocol invariant hidden state verifier-backed abstraction"
    else:
        manifest_path = str(
            (ROOT / "fixtures" / "quorum_commit" / "train" / "manifest.json").resolve()
        )
        evidence_query = "quorum commit invariant hidden state verifier-backed abstraction"
    proposal_system.configure_proposal_session(
        artifacts=[{"id": f"{family}_manifest_train", "manifest_path": manifest_path}],
        context={"manifest_paths": [manifest_path], "evidence_query": evidence_query},
        task_id=f"{family}_heuristic_runtime",
    )
    baseline_summary = baseline_system.run_until_stable()
    proposal_summary = proposal_system.run_until_stable()
    return row(
        system_name="heuristic_proposal_adapter",
        family=family,
        target_family=family,
        case_kind="proposal_runtime",
        mapping_class="source_invention",
        baseline_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        transfer_final_psi=float(proposal_summary.get("final_psi") or 0.0),
        contradiction_gain=float(
            (baseline_summary.get("final_psi") or 0.0) - (proposal_summary.get("final_psi") or 0.0)
        ),
        verifier_results=[],
        verifier_stack=[],
        source_runtime_metrics=runtime_row_fields(proposal_summary),
        accepted_interface_is_constant=None,
        proposal_adapter=adapter.__class__.__name__,
        artifact_version=artifact_version,
        extra={"positive_transfer": False},
    )


def _runtime_baseline_row(
    *,
    system_name: str,
    family: str,
    runtime_raw: dict[str, Any],
    artifact_version: dict[str, Any],
    assisted: bool,
) -> dict[str, Any]:
    baseline_summary = dict(runtime_raw.get("baseline", {}).get("summary", {}))
    proposal_summary = dict(runtime_raw.get("proposal_assisted", {}).get("summary", {}))
    active_summary = proposal_summary if assisted else baseline_summary
    return row(
        system_name=system_name,
        family=family,
        target_family=family,
        case_kind="proposal_runtime",
        mapping_class="source_invention",
        baseline_final_psi=float(baseline_summary.get("final_psi") or 0.0),
        transfer_final_psi=float(active_summary.get("final_psi") or 0.0),
        contradiction_gain=float(
            (baseline_summary.get("final_psi") or 0.0) - (active_summary.get("final_psi") or 0.0)
        ),
        verifier_results=[],
        verifier_stack=list(runtime_raw.get("proof_contract", {}).get("verifier_stack", [])),
        source_runtime_metrics=runtime_row_fields(active_summary),
        accepted_interface_is_constant=None,
        proposal_adapter=(
            runtime_raw.get("proposal_assisted", {}).get("adapter")
            if assisted
            else runtime_raw.get("baseline", {}).get("adapter")
        ),
        artifact_version=artifact_version,
        extra={
            "positive_transfer": False,
            "cycle_delta_from_no_proposals": runtime_raw.get("comparison", {}).get(
                "cycles_to_first_accepted_symbol_delta"
            ),
            "verifier_call_delta_from_no_proposals": runtime_raw.get("comparison", {}).get(
                "verifier_calls_to_acceptance_delta"
            ),
        },
    )


def run_gauntlet_benchmark(output_dir: str = "artifacts/phase7") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase7", root=ROOT)

    run_formal_protocol_benchmark(output_dir="artifacts/phase1")
    run_quorum_commit_benchmark(output_dir="artifacts/phase3")
    run_proposal_runtime_benchmark(output_dir="artifacts/phase2", family="protocol_guard")
    run_proposal_runtime_benchmark(output_dir="artifacts/phase4", family="quorum_commit")
    run_transfer_matrix_benchmark(output_dir="artifacts/phase4")

    paths = _source_paths()
    protocol_summary = load_json(paths["protocol_summary"])
    quorum_summary = load_json(paths["quorum_summary"])
    protocol_runtime_raw = load_json(paths["protocol_runtime"])
    quorum_runtime_raw = load_json(paths["quorum_runtime"])
    protocol_registry = OntologyRegistry.load(str(paths["protocol_registry"]))
    quorum_registry = OntologyRegistry.load(str(paths["quorum_registry"]))
    _, protocol_record = _first_accepted_record(protocol_registry)
    _, quorum_record = _first_accepted_record(quorum_registry)
    protocol_runtime = _proposal_runtime_metrics(paths["protocol_runtime"])
    quorum_runtime = _proposal_runtime_metrics(paths["quorum_runtime"])

    densn_rows = [
        _run_densn_transfer_case(
            source_family="protocol_guard",
            source_runtime_metrics=protocol_runtime,
            source_record=protocol_record,
            registry=protocol_registry,
            manifest_path=LEASE_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_lease_lock_graph_from_manifest,
            claim_kind=LEASE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(LEASE_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
        _run_densn_transfer_case(
            source_family="protocol_guard",
            source_runtime_metrics=protocol_runtime,
            source_record=protocol_record,
            registry=protocol_registry,
            manifest_path=SESSION_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_window_family_graph_from_manifest,
            claim_kind=SESSION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(SESSION_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
        _run_densn_transfer_case(
            source_family="protocol_guard",
            source_runtime_metrics=protocol_runtime,
            source_record=protocol_record,
            registry=protocol_registry,
            manifest_path=LEASE_FIXTURES_DIR / "negative_epoch" / "manifest.json",
            graph_builder=build_lease_lock_graph_from_manifest,
            claim_kind=LEASE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(LEASE_VERIFIER_SCRIPT)],
            artifact_version=version,
            case_kind="negative_transfer",
        ),
        _run_densn_transfer_case(
            source_family="quorum_commit",
            source_runtime_metrics=quorum_runtime,
            source_record=quorum_record,
            registry=quorum_registry,
            manifest_path=VOTE_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=VOTE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(VOTE_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
        _run_densn_transfer_case(
            source_family="quorum_commit",
            source_runtime_metrics=quorum_runtime,
            source_record=quorum_record,
            registry=quorum_registry,
            manifest_path=REPLICATION_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=REPLICATION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(REPLICATION_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
        _run_densn_transfer_case(
            source_family="quorum_commit",
            source_runtime_metrics=quorum_runtime,
            source_record=quorum_record,
            registry=quorum_registry,
            manifest_path=QUORUM_FIXTURES_DIR / "negative_commit_strict_3" / "manifest.json",
            graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=VOTE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(VOTE_VERIFIER_SCRIPT)],
            artifact_version=version,
            case_kind="negative_transfer",
        ),
        _run_invalid_cross_ladder_case(
            source_family="protocol_guard",
            source_runtime_metrics=protocol_runtime,
            source_record=protocol_record,
            manifest_path=VOTE_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=VOTE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(VOTE_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
        _run_invalid_cross_ladder_case(
            source_family="quorum_commit",
            source_runtime_metrics=quorum_runtime,
            source_record=quorum_record,
            manifest_path=SESSION_FIXTURES_DIR / "target" / "manifest.json",
            graph_builder=build_window_family_graph_from_manifest,
            claim_kind=SESSION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(SESSION_VERIFIER_SCRIPT)],
            artifact_version=version,
        ),
    ]

    baseline_rows = [
        _evaluate_model_baseline_row(
            system_name="live_model_tools_no_ontology",
            source_family="protocol_guard",
            source_manifest_path=ROOT / "fixtures" / "protocol_guard" / "train" / "manifest.json",
            target_manifest_path=LEASE_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_lease_lock_graph_from_manifest,
            claim_kind=LEASE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(LEASE_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=False,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_retrieval_verifiers",
            source_family="protocol_guard",
            source_manifest_path=ROOT / "fixtures" / "protocol_guard" / "train" / "manifest.json",
            target_manifest_path=LEASE_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_lease_lock_graph_from_manifest,
            claim_kind=LEASE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(LEASE_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=True,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_tools_no_ontology",
            source_family="protocol_guard",
            source_manifest_path=ROOT / "fixtures" / "protocol_guard" / "train" / "manifest.json",
            target_manifest_path=SESSION_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_window_family_graph_from_manifest,
            claim_kind=SESSION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(SESSION_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=False,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_retrieval_verifiers",
            source_family="protocol_guard",
            source_manifest_path=ROOT / "fixtures" / "protocol_guard" / "train" / "manifest.json",
            target_manifest_path=SESSION_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_window_family_graph_from_manifest,
            claim_kind=SESSION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(SESSION_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=True,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_tools_no_ontology",
            source_family="quorum_commit",
            source_manifest_path=ROOT / "fixtures" / "quorum_commit" / "train" / "manifest.json",
            target_manifest_path=VOTE_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=VOTE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(VOTE_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=False,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_retrieval_verifiers",
            source_family="quorum_commit",
            source_manifest_path=ROOT / "fixtures" / "quorum_commit" / "train" / "manifest.json",
            target_manifest_path=VOTE_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=VOTE_CLAIM_KIND,
            subprocess_command=[sys.executable, str(VOTE_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=True,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_tools_no_ontology",
            source_family="quorum_commit",
            source_manifest_path=ROOT / "fixtures" / "quorum_commit" / "train" / "manifest.json",
            target_manifest_path=REPLICATION_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=REPLICATION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(REPLICATION_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=False,
        ),
        _evaluate_model_baseline_row(
            system_name="live_model_retrieval_verifiers",
            source_family="quorum_commit",
            source_manifest_path=ROOT / "fixtures" / "quorum_commit" / "train" / "manifest.json",
            target_manifest_path=REPLICATION_FIXTURES_DIR / "target" / "manifest.json",
            target_graph_builder=build_commit_family_graph_from_manifest,
            claim_kind=REPLICATION_CLAIM_KIND,
            subprocess_command=[sys.executable, str(REPLICATION_VERIFIER_SCRIPT)],
            artifact_version=version,
            with_retrieval=True,
        ),
        _summary_row(
            system_name="graph_memory_without_tsl",
            family="protocol_guard",
            summary=dict(protocol_summary.get("baseline_no_tsl", {})),
            artifact_version=version,
            case_kind="source_ablation",
            mapping_class="no_tsl",
            verifier_stack=list(
                protocol_summary.get("proof_contract", {}).get("verifier_stack", [])
            ),
            proposal_adapter=protocol_summary.get("proof_contract", {}).get("proposal_adapter"),
            extra={"positive_transfer": False},
        ),
        _summary_row(
            system_name="graph_memory_without_tsl",
            family="quorum_commit",
            summary=dict(quorum_summary.get("baseline_no_tsl", {})),
            artifact_version=version,
            case_kind="source_ablation",
            mapping_class="no_tsl",
            verifier_stack=list(quorum_summary.get("proof_contract", {}).get("verifier_stack", [])),
            proposal_adapter=quorum_summary.get("proof_contract", {}).get("proposal_adapter"),
            extra={"positive_transfer": False},
        ),
        _summary_row(
            system_name="densn_without_conflict_memory",
            family="protocol_guard",
            summary=dict(protocol_summary.get("baseline_no_conflict_memory", {})),
            artifact_version=version,
            case_kind="source_ablation",
            mapping_class="no_conflict_memory",
            verifier_stack=list(
                protocol_summary.get("proof_contract", {}).get("verifier_stack", [])
            ),
            proposal_adapter=protocol_summary.get("proof_contract", {}).get("proposal_adapter"),
            extra={"positive_transfer": False},
        ),
        _summary_row(
            system_name="densn_without_conflict_memory",
            family="quorum_commit",
            summary=dict(quorum_summary.get("baseline_no_conflict_memory", {})),
            artifact_version=version,
            case_kind="source_ablation",
            mapping_class="no_conflict_memory",
            verifier_stack=list(quorum_summary.get("proof_contract", {}).get("verifier_stack", [])),
            proposal_adapter=quorum_summary.get("proof_contract", {}).get("proposal_adapter"),
            extra={"positive_transfer": False},
        ),
        _runtime_baseline_row(
            system_name="densn_without_proposal_assistance",
            family="protocol_guard",
            runtime_raw=protocol_runtime_raw,
            artifact_version=version,
            assisted=False,
        ),
        _runtime_baseline_row(
            system_name="densn_without_proposal_assistance",
            family="quorum_commit",
            runtime_raw=quorum_runtime_raw,
            artifact_version=version,
            assisted=False,
        ),
        _runtime_baseline_row(
            system_name="live_model_proposal_adapter",
            family="protocol_guard",
            runtime_raw=protocol_runtime_raw,
            artifact_version=version,
            assisted=True,
        ),
        _runtime_baseline_row(
            system_name="live_model_proposal_adapter",
            family="quorum_commit",
            runtime_raw=quorum_runtime_raw,
            artifact_version=version,
            assisted=True,
        ),
        _heuristic_runtime_row("protocol_guard", version),
        _heuristic_runtime_row("quorum_commit", version),
    ]

    all_rows = [*densn_rows, *baseline_rows]
    densn_positive_rows = [row_ for row_ in densn_rows if row_["case_kind"] == "positive_transfer"]
    densn_negative_rows = [row_ for row_ in densn_rows if row_["case_kind"] == "negative_transfer"]
    densn_cross_rows = [row_ for row_ in densn_rows if row_["case_kind"] == "cross_ladder_invalid"]
    verifier_rows = [row_ for row_ in densn_rows if row_["verifier_results"]]
    verifier_agreement_rate = 0.0
    if verifier_rows:
        verifier_agreement_rate = sum(
            1.0 if len({result["passed"] for result in row_["verifier_results"]}) == 1 else 0.0
            for row_ in verifier_rows
        ) / len(verifier_rows)
    runtime_reduction_values: list[float] = []
    for runtime_raw in (protocol_runtime_raw, quorum_runtime_raw):
        baseline_cycles = (
            runtime_raw.get("baseline", {})
            .get("summary", {})
            .get("runtime_metrics", {})
            .get("cycles_to_first_accepted_symbol")
        )
        proposal_cycles = (
            runtime_raw.get("proposal_assisted", {})
            .get("summary", {})
            .get("runtime_metrics", {})
            .get("cycles_to_first_accepted_symbol")
        )
        if baseline_cycles and proposal_cycles:
            runtime_reduction_values.append(
                (float(baseline_cycles) - float(proposal_cycles)) / float(baseline_cycles)
            )
    runtime_reduction_values.sort()
    live_proposal_cycle_reduction_median = 0.0
    if runtime_reduction_values:
        live_proposal_cycle_reduction_median = runtime_reduction_values[
            len(runtime_reduction_values) // 2
        ]
    interface_flags = [
        _interface_is_constant(protocol_record),
        bool(quorum_summary.get("accepted_interface_is_constant"))
        if quorum_summary.get("accepted_interface_is_constant") is not None
        else _interface_is_constant(quorum_record),
    ]
    non_constant_rate = sum(1 for flag in interface_flags if flag is False) / max(
        len(interface_flags), 1
    )
    model_baseline_rows = [
        row_
        for row_ in baseline_rows
        if row_["system"] in {"live_model_tools_no_ontology", "live_model_retrieval_verifiers"}
    ]
    model_baseline_pass_rate = sum(
        1 for row_ in model_baseline_rows if row_["verifier_status"] == "pass"
    ) / max(len(model_baseline_rows), 1)
    model_baseline_mean_verifier_calls = sum(
        float(row_.get("verifier_calls_to_acceptance") or 0.0) for row_ in model_baseline_rows
    ) / max(len(model_baseline_rows), 1)
    model_baseline_mean_contradiction_gain = sum(
        float(row_.get("contradiction_gain") or 0.0) for row_ in model_baseline_rows
    ) / max(len(model_baseline_rows), 1)
    model_baseline_mean_cycles_to_useful_outcome = sum(
        float(row_.get("cycles_to_useful_outcome") or 0.0) for row_ in model_baseline_rows
    ) / max(len(model_baseline_rows), 1)
    densn_mean_verifier_calls = sum(
        float(row_.get("verifier_calls_to_acceptance") or 0.0) for row_ in densn_positive_rows
    ) / max(len(densn_positive_rows), 1)
    densn_mean_contradiction_gain = sum(
        float(row_.get("contradiction_gain") or 0.0) for row_ in densn_positive_rows
    ) / max(len(densn_positive_rows), 1)
    densn_mean_cycles = sum(
        float(row_.get("cycles_to_first_accepted_symbol") or 0.0) for row_ in densn_positive_rows
    ) / max(len(densn_positive_rows), 1)
    densn_mean_cycles_to_useful_outcome = sum(
        float(row_.get("cycles_to_useful_outcome") or 0.0) for row_ in densn_positive_rows
    ) / max(len(densn_positive_rows), 1)

    summary = {
        "artifact_version": version,
        "proof_contract": {
            "core_mode": "core_frozen",
            "core_api_version": CORE_API_VERSION,
            "expected_core_api_version": CORE_API_VERSION,
            "migration_note": None,
            "proposal_adapter": {
                "adapters_used": sorted(
                    {
                        str(row_.get("proposal_adapter"))
                        for row_ in all_rows
                        if row_.get("proposal_adapter")
                    }
                )
            },
            "verifier_stack": sorted(
                {
                    str(result.get("verifier_name"))
                    for row_ in all_rows
                    for result in row_.get("verifier_results", [])
                    if result.get("verifier_name")
                }
            ),
        },
        "rows": all_rows,
        "summary_metrics": {
            "densn_positive_transfer_rate": sum(
                1 for row_ in densn_positive_rows if row_.get("positive_transfer")
            )
            / max(len(densn_positive_rows), 1),
            "densn_negative_block_rate": sum(
                1 for row_ in densn_negative_rows if row_["verifier_status"] == "fail"
            )
            / max(len(densn_negative_rows), 1),
            "densn_cross_ladder_block_rate": sum(
                1 for row_ in densn_cross_rows if row_["verifier_status"] == "fail"
            )
            / max(len(densn_cross_rows), 1),
            "live_proposal_cycle_reduction_median": live_proposal_cycle_reduction_median,
            "verifier_agreement_rate": verifier_agreement_rate,
            "accepted_interface_non_constant_rate": non_constant_rate,
            "transfer_metrics": transfer_metrics_summary(
                transfer_results=[
                    {
                        "verification": {"passed": bool(row_["positive_transfer"])},
                        "summary": {"final_psi": row_["transfer_final_psi"]},
                        "contradiction_gain": row_["contradiction_gain"] or 0.0,
                    }
                    for row_ in densn_positive_rows
                ]
            ),
            "baseline_superiority": {
                "densn_positive_transfer_pass_rate": sum(
                    1 for row_ in densn_positive_rows if row_["verifier_status"] == "pass"
                )
                / max(len(densn_positive_rows), 1),
                "model_baseline_transfer_pass_rate": model_baseline_pass_rate,
                "densn_mean_cycles_to_first_accepted_symbol": densn_mean_cycles,
                "model_baseline_mean_cycles_to_first_accepted_symbol": None,
                "densn_mean_cycles_to_useful_outcome": densn_mean_cycles_to_useful_outcome,
                "model_baseline_mean_cycles_to_useful_outcome": model_baseline_mean_cycles_to_useful_outcome,
                "densn_mean_verifier_calls_to_acceptance": densn_mean_verifier_calls,
                "model_baseline_mean_verifier_calls_to_acceptance": model_baseline_mean_verifier_calls,
                "densn_mean_contradiction_gain": densn_mean_contradiction_gain,
                "model_baseline_mean_contradiction_gain": model_baseline_mean_contradiction_gain,
            },
        },
        "checks": {
            "ladder_a_positive_targets": sum(
                1
                for row_ in densn_positive_rows
                if row_["family"] == "protocol_guard" and row_.get("positive_transfer")
            ),
            "ladder_b_positive_targets": sum(
                1
                for row_ in densn_positive_rows
                if row_["family"] == "quorum_commit" and row_.get("positive_transfer")
            ),
            "ladder_a_negative_blocks": sum(
                1
                for row_ in densn_negative_rows
                if row_["family"] == "protocol_guard" and row_["verifier_status"] == "fail"
            ),
            "ladder_b_negative_blocks": sum(
                1
                for row_ in densn_negative_rows
                if row_["family"] == "quorum_commit" and row_["verifier_status"] == "fail"
            ),
            "cross_ladder_blocks": sum(
                1 for row_ in densn_cross_rows if row_["verifier_status"] == "fail"
            ),
        },
    }
    write_json_artifact(target_dir / "gauntlet_summary.json", summary, version=version)
    write_text_artifact(
        target_dir / "gauntlet_report.md",
        "\n".join(
            [
                "# Phase 7 Gauntlet",
                "",
                f"- Positive transfers: `{summary['checks']['ladder_a_positive_targets'] + summary['checks']['ladder_b_positive_targets']}`",
                f"- Negative blocks: `{summary['checks']['ladder_a_negative_blocks'] + summary['checks']['ladder_b_negative_blocks']}`",
                f"- Cross-ladder blocks: `{summary['checks']['cross_ladder_blocks']}`",
                f"- Live proposal median cycle reduction: `{summary['summary_metrics']['live_proposal_cycle_reduction_median']}`",
                f"- DENSN transfer pass rate: `{summary['summary_metrics']['baseline_superiority']['densn_positive_transfer_pass_rate']}`",
                f"- Model baseline transfer pass rate: `{summary['summary_metrics']['baseline_superiority']['model_baseline_transfer_pass_rate']}`",
                f"- Verifier agreement rate: `{summary['summary_metrics']['verifier_agreement_rate']}`",
            ]
        ),
        version=version,
    )
    return summary
