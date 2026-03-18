"""Proposal quality benchmark under quarantine."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
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
    build_credit_window_graph_from_manifest,
    run_credit_window_benchmark,
)
from .credit_window import (
    train_manifest_path as credit_window_train_manifest_path,
)
from .etcd_raft_current_term import (
    MANIFEST_PATH as ETCD_MANIFEST_PATH,
)
from .etcd_raft_current_term import (
    _make_graph as etcd_make_graph,
)
from .etcd_raft_current_term import (
    run_real_world_etcd_raft_benchmark,
)
from .formal_protocol import (
    build_protocol_graph_from_manifest,
    run_formal_protocol_benchmark,
)
from .formal_protocol import (
    train_manifest_path as protocol_train_manifest_path,
)
from .quorum_commit import (
    build_quorum_graph_from_manifest,
    run_quorum_commit_benchmark,
)
from .quorum_commit import (
    train_manifest_path as quorum_train_manifest_path,
)
from .raft_rs_read_index_current_term import (
    MANIFEST_PATH as RAFT_RS_MANIFEST_PATH,
)
from .raft_rs_read_index_current_term import (
    _make_graph as raft_rs_make_graph,
)
from .raft_rs_read_index_current_term import (
    run_real_world_raft_rs_benchmark,
)
from .redislock_refresh import (
    MANIFEST_PATH as REDISLOCK_MANIFEST_PATH,
)
from .redislock_refresh import (
    _make_graph as redislock_make_graph,
)
from .redislock_refresh import (
    run_real_world_redislock_benchmark,
)
from .redsync_mutex_extend import (
    MANIFEST_PATH as REDSYNC_MANIFEST_PATH,
)
from .redsync_mutex_extend import (
    _make_graph as redsync_make_graph,
)
from .redsync_mutex_extend import (
    run_real_world_redsync_benchmark,
)

ROOT = Path(__file__).resolve().parents[2]


class StageTraceRecorder:
    def __init__(self, path: str | None) -> None:
        self.path = None if not path else Path(path)
        self.started_at = time.perf_counter()
        self.current_stage: str | None = None
        self.stage_timings: dict[str, float] = {}
        self.completed: list[str] = []
        if self.path is not None:
            self.flush_snapshot()

    def start(self, stage: str) -> None:
        self.current_stage = stage
        self.stage_started_at = time.perf_counter()
        self.flush_snapshot()

    def complete(self, stage: str) -> None:
        elapsed = time.perf_counter() - getattr(self, "stage_started_at", self.started_at)
        self.stage_timings[stage] = round(elapsed, 3)
        self.completed.append(stage)
        self.current_stage = None
        self.flush_snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_stage": self.current_stage,
            "completed_stages": list(self.completed),
            "stage_timings_seconds": dict(self.stage_timings),
            "elapsed_seconds": round(time.perf_counter() - self.started_at, 3),
        }

    def flush_snapshot(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")


def proposal_setup(family: str) -> dict[str, Any]:
    if family == "protocol_guard":
        manifest_path = str(protocol_train_manifest_path())
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/phase1",
            "benchmark_runner": run_formal_protocol_benchmark,
            "build_graph": lambda prefix: build_protocol_graph_from_manifest(
                protocol_train_manifest_path(),
                prefix=prefix,
                write_count=2,
            ),
            "artifacts": [{"id": "protocol_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "guard protocol invariant hidden state verifier-backed abstraction",
            },
            "task_id": "proposal_quality_protocol_guard",
        }
    if family == "quorum_commit":
        manifest_path = str(quorum_train_manifest_path())
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/phase3",
            "benchmark_runner": run_quorum_commit_benchmark,
            "build_graph": lambda prefix: build_quorum_graph_from_manifest(
                quorum_train_manifest_path(),
                prefix=prefix,
            ),
            "artifacts": [{"id": "quorum_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "quorum commit invariant hidden state verifier-backed abstraction",
            },
            "task_id": "proposal_quality_quorum_commit",
        }
    if family == "credit_window":
        manifest_path = str(credit_window_train_manifest_path())
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/phase12",
            "benchmark_runner": run_credit_window_benchmark,
            "build_graph": lambda prefix: build_credit_window_graph_from_manifest(
                credit_window_train_manifest_path(),
                prefix=prefix,
            ),
            "artifacts": [{"id": "credit_window_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "credit window invariant hidden state verifier-backed abstraction",
            },
            "task_id": "proposal_quality_credit_window",
        }
    if family == "etcd_raft_current_term":
        manifest_path = str(ETCD_MANIFEST_PATH)
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/real_world",
            "benchmark_runner": run_real_world_etcd_raft_benchmark,
            "build_graph": lambda prefix: etcd_make_graph(prefix),
            "artifacts": [{"id": "etcd_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "etcd raft current term commit invariant hidden state quorum current term",
            },
            "task_id": "proposal_quality_etcd_raft_current_term",
        }
    if family == "raft_rs_read_index_current_term":
        manifest_path = str(RAFT_RS_MANIFEST_PATH)
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/real_world",
            "benchmark_runner": run_real_world_raft_rs_benchmark,
            "build_graph": lambda prefix: raft_rs_make_graph(prefix),
            "artifacts": [{"id": "raft_rs_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "raft rs read index current term invariant hidden state quorum leader",
            },
            "task_id": "proposal_quality_raft_rs_read_index_current_term",
        }
    if family == "redsync_mutex_extend":
        manifest_path = str(REDSYNC_MANIFEST_PATH)
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/real_world",
            "benchmark_runner": run_real_world_redsync_benchmark,
            "build_graph": lambda prefix: redsync_make_graph(prefix),
            "artifacts": [{"id": "redsync_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "redsync mutex extend invariant hidden state lock live extend window",
            },
            "task_id": "proposal_quality_redsync_mutex_extend",
        }
    if family == "redislock_refresh":
        manifest_path = str(REDISLOCK_MANIFEST_PATH)
        return {
            "family": family,
            "manifest_path": manifest_path,
            "benchmark_output_dir": "artifacts/real_world",
            "benchmark_runner": run_real_world_redislock_benchmark,
            "build_graph": lambda prefix: redislock_make_graph(prefix),
            "artifacts": [{"id": "redislock_manifest_train", "manifest_path": manifest_path}],
            "context": {
                "manifest_paths": [manifest_path],
                "evidence_query": "redislock refresh invariant hidden state lock live refresh window",
            },
            "task_id": "proposal_quality_redislock_refresh",
        }
    raise ValueError(f"Unsupported proposal-quality family: {family}")


def proposal_text(proposal: ProposalRecord) -> str:
    return json.dumps(proposal.payload, sort_keys=True).lower()


def normalized_label(proposal: ProposalRecord) -> str:
    return "".join(
        character
        for character in str(proposal.payload.get("label", "")).lower()
        if character.isalnum()
    )


def is_useful_proposal(
    proposal: ProposalRecord,
    accepted_record: dict[str, Any],
    *,
    family: str,
) -> bool:
    text = proposal_text(proposal)
    compact_text = "".join(character for character in text if character.isalnum())
    parent_roles = set(accepted_record.get("reuse_signature", {}).get("parent_roles", []))
    blanket_roles = set(accepted_record.get("reuse_signature", {}).get("blanket_roles", []))
    role_hits = any(role in text for role in parent_roles | blanket_roles)

    if family == "protocol_guard":
        if proposal.proposal_type == "atom":
            return "guard_state" in text
        if proposal.proposal_type == "constraint":
            return "write" in text and "guard" in text
        if proposal.proposal_type == "hidden_variable":
            return "guard_active" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and normalized_label(proposal) == "writeguard"
        if proposal.proposal_type == "test":
            return (
                "write_after_end" in text
                or "end_before_begin" in text
                or "write_without_begin" in text
            )
        if proposal.proposal_type == "evidence_query":
            return "guard" in text or "invariant" in text
        return False

    if family == "quorum_commit":
        if proposal.proposal_type == "atom":
            return "commit_ready" in text
        if proposal.proposal_type == "constraint":
            return "commit" in text and (
                "ack" in text or "clear" in text or "quorum" in text or "ready" in text
            )
        if proposal.proposal_type == "hidden_variable":
            return "commit_ready" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and normalized_label(proposal) == "commitready"
        if proposal.proposal_type == "test":
            return (
                "commit_without_quorum" in text
                or "commit_without_clear" in text
                or "commit_with_single_ack" in text
                or "stale_commit_attempt" in text
            )
        if proposal.proposal_type == "evidence_query":
            return "quorum" in text or "commit" in text or "invariant" in text or "ready" in text
    if family == "credit_window":
        if proposal.proposal_type == "atom":
            return "credit_live" in text
        if proposal.proposal_type == "constraint":
            return "charge" in text and ("credit" in text or "balance" in text)
        if proposal.proposal_type == "hidden_variable":
            return "credit_live" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and normalized_label(proposal) == "creditlive"
        if proposal.proposal_type == "test":
            return (
                "charge_without_balance" in text
                or "charge_after_revoke" in text
                or "charge_without_grant" in text
            )
        if proposal.proposal_type == "evidence_query":
            return "credit" in text or "invariant" in text or "balance" in text
    if family == "etcd_raft_current_term":
        if proposal.proposal_type == "atom":
            return (
                "current_term" in text
                or "leader_ready" in text
                or "quorum_ready" in text
                or "committedentryincurrentterm" in compact_text
            )
        if proposal.proposal_type == "constraint":
            return ("commit" in text or "advance" in text) and (
                "current_term" in text or "quorum" in text or "replica" in text
            )
        if proposal.proposal_type == "hidden_variable":
            return (
                "current_term" in text
                or "commit_ready" in text
                or "leader_commit_ready" in text
                or "committedentryincurrentterm" in compact_text
                or "highestcommittedterm" in compact_text
                or ("committed" in text and "term" in text)
            )
        if proposal.proposal_type == "semantic_label":
            return role_hits and (
                normalized_label(proposal)
                in {"currenttermcommitready", "raftcurrenttermcommitready"}
            )
        if proposal.proposal_type == "test":
            return (
                "current_term" in text
                or "read_index" in text
                or "prior_term" in text
                or "quorum" in text
                or "previoustermcase" in compact_text
                or "commitslogfromcurrentterm" in compact_text
            )
        if proposal.proposal_type == "evidence_query":
            return (
                "current term" in text or "commit" in text or "quorum" in text or "replica" in text
            )
    if family == "raft_rs_read_index_current_term":
        if proposal.proposal_type == "atom":
            return "current_term" in text or "read_index" in text or "leader_ready" in text
        if proposal.proposal_type == "constraint":
            return (
                ("read" in text or "accept" in text)
                and ("current_term" in text or "append" in text or "leader" in text)
            ) or "committocurrentterm" in compact_text
        if proposal.proposal_type == "hidden_variable":
            return "current_term" in text or "read_ready" in text or "read_index_ready" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and (
                normalized_label(proposal)
                in {
                    "currenttermreadindexready",
                    "raftrsreadindexready",
                    "leaderreadindexready",
                }
            )
        if proposal.proposal_type == "test":
            return "read_index" in text or "current_term" in text or "append" in text
        if proposal.proposal_type == "evidence_query":
            return "read index" in text or "current term" in text or "leader" in text
    if family == "redsync_mutex_extend":
        if proposal.proposal_type == "atom":
            return "lock_live" in text or "extend_window" in text
        if proposal.proposal_type == "constraint":
            return (
                "extend" in text and ("lock" in text or "window" in text or "live" in text)
            ) or "mutexlive" in compact_text
        if proposal.proposal_type == "hidden_variable":
            return "lock_live" in text or "extend_window" in text or "mutex_live" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and (
                normalized_label(proposal) in {"extendwindowready", "redsyncextendwindow"}
            )
        if proposal.proposal_type == "test":
            return "extend" in text and ("expired" in text or "unlock" in text or "lock" in text)
        if proposal.proposal_type == "evidence_query":
            return "extend" in text or "lock" in text or "window" in text or "mutex" in text
    if family == "redislock_refresh":
        if proposal.proposal_type == "atom":
            return "lock_live" in text or "refresh_window" in text or "refresh_ready" in text
        if proposal.proposal_type == "constraint":
            return (
                "refresh" in text and ("lock" in text or "window" in text or "live" in text)
            ) or ("obtain" in text and "lock_live" in text)
        if proposal.proposal_type == "hidden_variable":
            return "lock_live" in text or "refresh_window" in text or "refresh_ready" in text
        if proposal.proposal_type == "semantic_label":
            return role_hits and (
                normalized_label(proposal) in {"refreshwindowready", "redislockrefreshwindow"}
            )
        if proposal.proposal_type == "test":
            return "refresh" in text and (
                "expired" in text or "release" in text or "obtain" in text
            )
        if proposal.proposal_type == "evidence_query":
            return "refresh" in text or "lock" in text or "window" in text or "obtain" in text
    return False


def run_proposal_quality_benchmark(
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
    stage_trace = StageTraceRecorder(os.getenv("DENSN_STAGE_TRACE_PATH"))

    stage_trace.start("benchmark_runner")
    setup = proposal_setup(family)
    benchmark_summary = setup["benchmark_runner"](output_dir=setup["benchmark_output_dir"])
    stage_trace.complete("benchmark_runner")
    accepted_record = benchmark_summary["accepted_record"]
    if accepted_record is None:
        raise RuntimeError(f"{family} benchmark did not produce an accepted symbol.")

    stage_trace.start("graph_setup")
    prefix = {
        "protocol_guard": "PROPOSAL_QUALITY",
        "quorum_commit": "PROPOSAL_QUALITY_QUORUM",
        "credit_window": "PROPOSAL_QUALITY_CREDIT_WINDOW",
        "etcd_raft_current_term": "PROPOSAL_QUALITY_ETCD_RAFT",
        "raft_rs_read_index_current_term": "PROPOSAL_QUALITY_RAFT_RS",
        "redsync_mutex_extend": "PROPOSAL_QUALITY_REDSYNC",
        "redislock_refresh": "PROPOSAL_QUALITY_REDISLOCK",
    }.get(family, "PROPOSAL_QUALITY_GENERIC")
    graph = setup["build_graph"](prefix)
    system = DENSNSystem(graph)
    stage_trace.complete("graph_setup")

    stage_trace.start("adapter_setup")
    adapter = adapter_override or build_transformer_adapter_from_env(
        fallback=ArtifactHeuristicTransformerAdapter()
    )
    if adapter is None:
        raise RuntimeError("No transformer adapter is available.")
    system.set_transformer_adapter(adapter)
    system.register_proposal_reviewer(reviewer or ArtifactStructuralProposalReviewer())
    stage_trace.complete("adapter_setup")

    before = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
    artifacts = setup["artifacts"]
    context = setup["context"]
    stage_trace.start("proposal_generation")
    proposal_ids = system.transformer_propose(
        artifacts=artifacts,
        context=context,
        task_id=setup["task_id"],
    )
    stage_trace.complete("proposal_generation")
    stage_trace.start("proposal_review")
    system.review_pending_proposals(artifacts=artifacts, context=context)
    stage_trace.complete("proposal_review")

    stage_trace.start("metrics")
    reviewed: list[dict[str, Any]] = []
    useful_total = 0
    useful_accepted = 0
    accepted_count = 0
    for proposal_id in proposal_ids:
        proposal = system.proposal_quarantine.get(proposal_id)
        useful = is_useful_proposal(proposal, accepted_record, family=family)
        if useful:
            useful_total += 1
        if proposal.status == "accepted_for_structural_eval":
            accepted_count += 1
            if useful:
                useful_accepted += 1
        reviewed.append(
            {
                "proposal_id": proposal.id,
                "proposal_type": proposal.proposal_type,
                "source": proposal.source,
                "status": proposal.status,
                "review_reason": proposal.review_reason,
                "useful": useful,
                "payload": proposal.payload,
                "metadata": proposal.metadata,
            }
        )

    after = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
    total = len(proposal_ids)
    naive_precision = useful_total / total if total else 0.0
    triage_precision = useful_accepted / accepted_count if accepted_count else 0.0
    useful_recall = useful_accepted / useful_total if useful_total else 0.0
    false_accept_rate = (
        (accepted_count - useful_accepted) / accepted_count if accepted_count else 0.0
    )
    stage_trace.complete("metrics")

    summary = {
        "family": family,
        "artifact_version": version,
        "proof_contract": {
            **system.core_contract(),
            "runtime_metrics": system.runtime_metrics(),
            "lifecycle_metrics": system.registry.lifecycle_summary(),
            "transfer_metrics": transfer_metrics_summary(),
        },
        "accepted_meta_symbol_id": benchmark_summary["accepted_meta_symbol_id"],
        "proposal_ids": proposal_ids,
        "reviewed_proposals": reviewed,
        "proposal_summary": system.proposal_summary(),
        "telemetry_summary": system.telemetry.summary(),
        "adapter": adapter.__class__.__name__,
        "graph_before": before,
        "graph_after": after,
        "ontology_mutated_directly": before != after,
        "stage_trace": stage_trace.snapshot(),
        "metrics": {
            "total_proposals": total,
            "useful_proposals_total": useful_total,
            "accepted_for_structural_eval": accepted_count,
            "useful_accepted": useful_accepted,
            "naive_accept_all_precision": naive_precision,
            "triage_precision": triage_precision,
            "useful_recall": useful_recall,
            "false_accept_rate": false_accept_rate,
        },
    }
    summary_name = (
        "proposal_quality_summary.json"
        if family == "protocol_guard"
        else "quorum_proposal_quality_summary.json"
        if family == "quorum_commit"
        else "credit_window_proposal_quality_summary.json"
        if family == "credit_window"
        else "etcd_raft_current_term_proposal_quality_summary.json"
        if family == "etcd_raft_current_term"
        else "raft_rs_read_index_current_term_proposal_quality_summary.json"
        if family == "raft_rs_read_index_current_term"
        else "redsync_mutex_extend_proposal_quality_summary.json"
        if family == "redsync_mutex_extend"
        else "redislock_refresh_proposal_quality_summary.json"
    )
    write_json_artifact(target_dir / summary_name, summary, version=version)
    return summary
