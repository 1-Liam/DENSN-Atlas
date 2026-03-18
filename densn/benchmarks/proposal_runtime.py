"""Measure in-loop proposal value under the shared DENSN runtime path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..lifecycle import VerifierBackedReuseEvaluator
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..proposal_review import ArtifactStructuralProposalReviewer, ProposalReviewer
from ..records import ProposalRecord
from ..system import DENSNSystem
from ..transformer import (
    ArtifactHeuristicTransformerAdapter,
    TransformerAdapter,
    build_transformer_adapter_from_env,
)
from .credit_window import (
    _graph_builder as credit_window_graph_builder,
)
from .credit_window import (
    _heldout_claim as credit_window_heldout_claim,
)
from .credit_window import (
    _register_verifier as register_credit_window_verifier,
)
from .credit_window import (
    _training_claim as credit_window_training_claim,
)
from .credit_window import (
    build_credit_window_graph_from_manifest,
    credit_window_config,
)
from .credit_window import (
    heldout_specs as credit_window_heldout_specs,
)
from .credit_window import (
    no_tsl_config as credit_window_no_tsl_config,
)
from .credit_window import (
    reuse_only_config as credit_window_reuse_only_config,
)
from .credit_window import (
    train_manifest_path as credit_window_train_manifest_path,
)
from .etcd_raft_current_term import (
    MANIFEST_PATH as ETCD_MANIFEST_PATH,
)
from .etcd_raft_current_term import (
    _candidate_evaluator as etcd_candidate_evaluator,
)
from .etcd_raft_current_term import (
    _make_graph as etcd_make_graph,
)
from .etcd_raft_current_term import (
    _register_verifiers as register_etcd_verifiers,
)
from .etcd_raft_current_term import (
    real_world_config as etcd_real_world_config,
)
from .formal_protocol import (
    _graph_builder,
    _heldout_claim,
    _register_protocol_verifier,
    _training_claim,
    build_protocol_graph_from_manifest,
    heldout_specs,
    no_tsl_config,
    protocol_config,
    reuse_only_config,
)
from .formal_protocol import (
    train_manifest_path as protocol_train_manifest_path,
)
from .quorum_commit import (
    _graph_builder as quorum_graph_builder,
)
from .quorum_commit import (
    _heldout_claim as quorum_heldout_claim,
)
from .quorum_commit import (
    _register_quorum_verifier,
    build_quorum_graph_from_manifest,
    quorum_config,
)
from .quorum_commit import (
    _training_claim as quorum_training_claim,
)
from .quorum_commit import (
    heldout_specs as quorum_heldout_specs,
)
from .quorum_commit import (
    no_tsl_config as quorum_no_tsl_config,
)
from .quorum_commit import (
    reuse_only_config as quorum_reuse_only_config,
)
from .quorum_commit import (
    train_manifest_path as quorum_train_manifest_path,
)
from .raft_rs_read_index_current_term import (
    MANIFEST_PATH as RAFT_RS_MANIFEST_PATH,
)
from .raft_rs_read_index_current_term import (
    _candidate_evaluator as raft_rs_candidate_evaluator,
)
from .raft_rs_read_index_current_term import (
    _make_graph as raft_rs_make_graph,
)
from .raft_rs_read_index_current_term import (
    _register_verifiers as register_raft_rs_verifiers,
)
from .raft_rs_read_index_current_term import (
    real_world_config as raft_rs_real_world_config,
)
from .redislock_refresh import (
    MANIFEST_PATH as REDISLOCK_MANIFEST_PATH,
)
from .redislock_refresh import (
    _candidate_evaluator as redislock_candidate_evaluator,
)
from .redislock_refresh import (
    _make_graph as redislock_make_graph,
)
from .redislock_refresh import (
    _register_verifiers as register_redislock_verifiers,
)
from .redislock_refresh import (
    real_world_config as redislock_real_world_config,
)
from .redsync_mutex_extend import (
    MANIFEST_PATH as REDSYNC_MANIFEST_PATH,
)
from .redsync_mutex_extend import (
    _candidate_evaluator as redsync_candidate_evaluator,
)
from .redsync_mutex_extend import (
    _make_graph as redsync_make_graph,
)
from .redsync_mutex_extend import (
    _register_verifiers as register_redsync_verifiers,
)
from .redsync_mutex_extend import (
    real_world_config as redsync_real_world_config,
)

ROOT = Path(__file__).resolve().parents[2]


class ReplayProposalAdapter(TransformerAdapter):
    def __init__(self, proposals: list[ProposalRecord]) -> None:
        self.proposals_by_type: dict[str, list[ProposalRecord]] = {}
        for proposal in proposals:
            self.proposals_by_type.setdefault(proposal.proposal_type, []).append(
                self.clone_proposal(proposal)
            )

    def clone_proposal(self, proposal: ProposalRecord) -> ProposalRecord:
        return ProposalRecord(
            id=proposal.id,
            proposal_type=proposal.proposal_type,
            source=proposal.source,
            payload=dict(proposal.payload),
            task_id=proposal.task_id,
            metadata=dict(proposal.metadata),
        )

    def typed_proposals(self, proposal_type: str) -> list[ProposalRecord]:
        return [
            self.clone_proposal(proposal)
            for proposal in self.proposals_by_type.get(proposal_type, [])
        ]

    def extract_atoms(
        self, artifacts: list[dict], task_id: str | None = None
    ) -> list[ProposalRecord]:
        return self.typed_proposals("atom")

    def extract_constraints(
        self, artifacts: list[dict], task_id: str | None = None
    ) -> list[ProposalRecord]:
        return self.typed_proposals("constraint")

    def propose_hidden_variables(
        self, context: dict, task_id: str | None = None
    ) -> list[ProposalRecord]:
        return self.typed_proposals("hidden_variable")

    def propose_labels(self, context: dict, task_id: str | None = None) -> list[ProposalRecord]:
        return self.typed_proposals("semantic_label")

    def generate_tests(
        self, claim: dict, context: dict, task_id: str | None = None
    ) -> list[ProposalRecord]:
        return self.typed_proposals("test")

    def retrieve_evidence(self, query: str, task_id: str | None = None) -> list[ProposalRecord]:
        return self.typed_proposals("evidence_query")


def _build_train_system(
    registry: OntologyRegistry,
    *,
    with_proposals: bool,
    family: str,
    reviewer: ProposalReviewer | None = None,
    adapter_override: TransformerAdapter | None = None,
) -> tuple[DENSNSystem, str]:
    if family == "protocol_guard":
        manifest_path = protocol_train_manifest_path()
        train_graph = build_protocol_graph_from_manifest(
            manifest_path,
            prefix="TRAIN_PROTOCOL_PROPOSAL_ON"
            if with_proposals
            else "TRAIN_PROTOCOL_PROPOSAL_OFF",
        )
        system = DENSNSystem(train_graph, protocol_config(), registry=registry)
        _register_protocol_verifier(system)
        system.register_candidate_evaluator(
            VerifierBackedReuseEvaluator(
                heldout_tasks=heldout_specs(),
                graph_builder=_graph_builder,
                verifier_registrar=_register_protocol_verifier,
                training_claim_builder=_training_claim,
                heldout_claim_builder=_heldout_claim,
                baseline_config=no_tsl_config(),
                reuse_config=reuse_only_config(),
            )
        )
        evidence_query = "guard protocol invariant hidden state verifier-backed abstraction"
        task_id = "protocol_guard_train"
    elif family == "quorum_commit":
        manifest_path = quorum_train_manifest_path()
        train_graph = build_quorum_graph_from_manifest(
            manifest_path,
            prefix="TRAIN_QUORUM_PROPOSAL_ON" if with_proposals else "TRAIN_QUORUM_PROPOSAL_OFF",
        )
        system = DENSNSystem(train_graph, quorum_config(), registry=registry)
        _register_quorum_verifier(system)
        system.register_candidate_evaluator(
            VerifierBackedReuseEvaluator(
                heldout_tasks=quorum_heldout_specs(),
                graph_builder=quorum_graph_builder,
                verifier_registrar=_register_quorum_verifier,
                training_claim_builder=quorum_training_claim,
                heldout_claim_builder=quorum_heldout_claim,
                baseline_config=quorum_no_tsl_config(),
                reuse_config=quorum_reuse_only_config(),
            )
        )
        evidence_query = "quorum commit invariant hidden state verifier-backed abstraction"
        task_id = "quorum_commit_train"
    elif family == "credit_window":
        manifest_path = credit_window_train_manifest_path()
        train_graph = build_credit_window_graph_from_manifest(
            manifest_path,
            prefix="TRAIN_CREDIT_PROPOSAL_ON" if with_proposals else "TRAIN_CREDIT_PROPOSAL_OFF",
        )
        system = DENSNSystem(train_graph, credit_window_config(), registry=registry)
        register_credit_window_verifier(system)
        system.register_candidate_evaluator(
            VerifierBackedReuseEvaluator(
                heldout_tasks=credit_window_heldout_specs(),
                graph_builder=credit_window_graph_builder,
                verifier_registrar=register_credit_window_verifier,
                training_claim_builder=credit_window_training_claim,
                heldout_claim_builder=credit_window_heldout_claim,
                baseline_config=credit_window_no_tsl_config(),
                reuse_config=credit_window_reuse_only_config(),
            )
        )
        evidence_query = "credit window invariant hidden state verifier-backed abstraction"
        task_id = "credit_window_train"
    elif family == "etcd_raft_current_term":
        manifest_path = ETCD_MANIFEST_PATH
        train_graph = etcd_make_graph(
            "TRAIN_ETCD_PROPOSAL_ON" if with_proposals else "TRAIN_ETCD_PROPOSAL_OFF"
        )
        system = DENSNSystem(train_graph, etcd_real_world_config(), registry=registry)
        register_etcd_verifiers(system)
        system.register_candidate_evaluator(etcd_candidate_evaluator)
        evidence_query = "etcd raft current term commit invariant hidden state quorum current term"
        task_id = "etcd_raft_current_term_train"
    elif family == "raft_rs_read_index_current_term":
        manifest_path = RAFT_RS_MANIFEST_PATH
        train_graph = raft_rs_make_graph(
            "TRAIN_RAFT_RS_PROPOSAL_ON" if with_proposals else "TRAIN_RAFT_RS_PROPOSAL_OFF"
        )
        system = DENSNSystem(train_graph, raft_rs_real_world_config(), registry=registry)
        register_raft_rs_verifiers(system)
        system.register_candidate_evaluator(raft_rs_candidate_evaluator)
        evidence_query = "raft rs read index current term invariant hidden state quorum leader"
        task_id = "raft_rs_read_index_current_term_train"
    elif family == "redsync_mutex_extend":
        manifest_path = REDSYNC_MANIFEST_PATH
        train_graph = redsync_make_graph(
            "TRAIN_REDSYNC_PROPOSAL_ON" if with_proposals else "TRAIN_REDSYNC_PROPOSAL_OFF"
        )
        system = DENSNSystem(train_graph, redsync_real_world_config(), registry=registry)
        register_redsync_verifiers(system)
        system.register_candidate_evaluator(redsync_candidate_evaluator)
        evidence_query = "redsync mutex extend invariant hidden state lock live extend window"
        task_id = "redsync_mutex_extend_train"
    elif family == "redislock_refresh":
        manifest_path = REDISLOCK_MANIFEST_PATH
        train_graph = redislock_make_graph(
            "TRAIN_REDISLOCK_PROPOSAL_ON" if with_proposals else "TRAIN_REDISLOCK_PROPOSAL_OFF"
        )
        system = DENSNSystem(train_graph, redislock_real_world_config(), registry=registry)
        register_redislock_verifiers(system)
        system.register_candidate_evaluator(redislock_candidate_evaluator)
        evidence_query = "redislock refresh invariant hidden state lock live refresh window"
        task_id = "redislock_refresh_train"
    else:
        raise ValueError(f"Unsupported proposal-runtime family: {family}")

    adapter_name = "none"
    if with_proposals:
        adapter = adapter_override or build_transformer_adapter_from_env(
            fallback=ArtifactHeuristicTransformerAdapter()
        )
        if adapter is None:
            raise RuntimeError("No transformer adapter is available.")
        adapter_name = adapter.__class__.__name__
        system.set_transformer_adapter(adapter)
        system.register_proposal_reviewer(reviewer or ArtifactStructuralProposalReviewer())
        manifest_path = str(manifest_path)
        system.configure_proposal_session(
            artifacts=[{"id": f"{family}_manifest_train", "manifest_path": manifest_path}],
            context={
                "manifest_paths": [manifest_path],
                "evidence_query": evidence_query,
            },
            task_id=task_id,
        )
    return system, adapter_name


def run_proposal_runtime_benchmark(
    output_dir: str = "artifacts/phase2",
    *,
    family: str = "protocol_guard",
    reviewer: ProposalReviewer | None = None,
    adapter_override: TransformerAdapter | None = None,
) -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    phase = {
        "protocol_guard": "phase2",
        "quorum_commit": "phase4",
        "credit_window": "phase13",
        "etcd_raft_current_term": "real_world",
        "raft_rs_read_index_current_term": "real_world",
        "redsync_mutex_extend": "real_world",
        "redislock_refresh": "real_world",
    }.get(family, "phase2")
    version = artifact_version_info(phase, root=ROOT)

    baseline_registry = OntologyRegistry()
    baseline_system, baseline_adapter = _build_train_system(
        baseline_registry,
        with_proposals=False,
        family=family,
        reviewer=reviewer,
    )
    baseline_summary = baseline_system.run_until_stable()

    proposal_registry = OntologyRegistry()
    proposal_system, proposal_adapter = _build_train_system(
        proposal_registry,
        with_proposals=True,
        family=family,
        reviewer=reviewer,
        adapter_override=adapter_override,
    )
    proposal_summary = proposal_system.run_until_stable()

    baseline_metrics = dict(baseline_summary.get("runtime_metrics", {}))
    proposal_metrics = dict(proposal_summary.get("runtime_metrics", {}))
    baseline_cycles = baseline_metrics.get("cycles_to_first_accepted_symbol")
    proposal_cycles = proposal_metrics.get("cycles_to_first_accepted_symbol")
    cycle_improvement = None
    if baseline_cycles is not None and proposal_cycles is not None:
        cycle_improvement = int(baseline_cycles) - int(proposal_cycles)

    summary = {
        "family": family,
        "artifact_version": version,
        "proof_contract": {
            **proposal_system.core_contract(),
            "runtime_metrics": proposal_summary.get("runtime_metrics", {}),
            "lifecycle_metrics": proposal_registry.lifecycle_summary(),
            "transfer_metrics": transfer_metrics_summary(),
        },
        "baseline": {
            "adapter": baseline_adapter,
            "summary": baseline_summary,
            "proposal_summary": baseline_system.proposal_summary(),
        },
        "proposal_assisted": {
            "adapter": proposal_adapter,
            "summary": proposal_summary,
            "proposal_summary": proposal_system.proposal_summary(),
        },
        "comparison": {
            "cycles_to_first_accepted_symbol_delta": cycle_improvement,
            "verifier_calls_to_acceptance_delta": (
                int(baseline_metrics.get("verifier_calls_to_acceptance", 0))
                - int(proposal_metrics.get("verifier_calls_to_acceptance", 0))
            ),
            "false_candidate_delta": (
                int(baseline_metrics.get("false_candidate_count_before_acceptance", 0))
                - int(proposal_metrics.get("false_candidate_count_before_acceptance", 0))
            ),
            "rollback_delta": (
                int(baseline_metrics.get("rollback_count_before_acceptance", 0))
                - int(proposal_metrics.get("rollback_count_before_acceptance", 0))
            ),
            "max_proposal_support": proposal_metrics.get("max_proposal_support", 0.0),
        },
    }
    summary_name = (
        "proposal_runtime_summary.json"
        if family == "protocol_guard"
        else "quorum_proposal_runtime_summary.json"
        if family == "quorum_commit"
        else "credit_window_proposal_runtime_summary.json"
        if family == "credit_window"
        else "etcd_raft_current_term_proposal_runtime_summary.json"
        if family == "etcd_raft_current_term"
        else "raft_rs_read_index_current_term_proposal_runtime_summary.json"
        if family == "raft_rs_read_index_current_term"
        else "redsync_mutex_extend_proposal_runtime_summary.json"
        if family == "redsync_mutex_extend"
        else "redislock_refresh_proposal_runtime_summary.json"
    )
    write_json_artifact(target_dir / summary_name, summary, version=version)
    return summary
