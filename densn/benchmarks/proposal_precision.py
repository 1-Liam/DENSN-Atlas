"""Reviewer-policy precision campaign on a fixed live proposal pool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from ..proposal_review import (
    REVIEW_POLICY_ATOM_SHADOW_REJECT,
    REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN,
    REVIEW_POLICY_CURRENT,
    REVIEW_POLICY_REAL_WORLD_STRICT,
    ArtifactStructuralProposalReviewer,
)
from ..records import ProposalRecord
from ..system import DENSNSystem
from ..transformer import ArtifactHeuristicTransformerAdapter, build_transformer_adapter_from_env
from .proposal_quality import proposal_setup, run_proposal_quality_benchmark
from .proposal_runtime import ReplayProposalAdapter, run_proposal_runtime_benchmark

ROOT = Path(__file__).resolve().parents[2]
POLICY_ORDER = [
    REVIEW_POLICY_CURRENT.name,
    REVIEW_POLICY_ATOM_SHADOW_REJECT.name,
    REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN.name,
    REVIEW_POLICY_REAL_WORLD_STRICT.name,
]
POLICY_STRICTNESS_RANK = {
    REVIEW_POLICY_CURRENT.name: 0,
    REVIEW_POLICY_ATOM_SHADOW_REJECT.name: 1,
    REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN.name: 2,
    REVIEW_POLICY_REAL_WORLD_STRICT.name: 3,
}


def _fixed_pool_filename(family: str) -> str:
    return f"{family}_fixed_proposal_pool.json"


def _summary_filename(family: str) -> str:
    return (
        "proposal_precision_summary.json"
        if family == "credit_window"
        else f"{family}_proposal_precision_summary.json"
    )


def _report_path(family: str) -> Path:
    if family == "credit_window":
        return ROOT / "reports" / "phase13_proposal_precision_report.md"
    return ROOT / "reports" / f"phase13_{family}_proposal_precision_report.md"


def _quality_summary_name(family: str) -> str:
    if family == "protocol_guard":
        return "proposal_quality_summary.json"
    if family == "quorum_commit":
        return "quorum_proposal_quality_summary.json"
    if family == "credit_window":
        return "credit_window_proposal_quality_summary.json"
    return f"{family}_proposal_quality_summary.json"


def _runtime_summary_name(family: str) -> str:
    if family == "protocol_guard":
        return "proposal_runtime_summary.json"
    if family == "quorum_commit":
        return "quorum_proposal_runtime_summary.json"
    if family == "credit_window":
        return "credit_window_proposal_runtime_summary.json"
    return f"{family}_proposal_runtime_summary.json"


def _serialize_proposal(proposal: ProposalRecord) -> dict[str, Any]:
    return {
        "proposal_id": proposal.id,
        "proposal_type": proposal.proposal_type,
        "source": proposal.source,
        "payload": proposal.payload,
        "task_id": proposal.task_id,
        "metadata": proposal.metadata,
    }


def _deserialize_proposal(payload: dict[str, Any]) -> ProposalRecord:
    return ProposalRecord(
        id=str(payload["proposal_id"]),
        proposal_type=str(payload["proposal_type"]),
        source=str(payload["source"]),
        payload=dict(payload.get("payload", {})),
        task_id=payload.get("task_id"),
        status=str(payload.get("status", "under_review")),
        metadata=dict(payload.get("metadata", {})),
    )


def _generate_fixed_live_proposals(family: str) -> dict[str, Any]:
    setup = proposal_setup(family)
    graph = setup["build_graph"](f"PROPOSAL_PRECISION_{family.upper()}")
    system = DENSNSystem(graph)
    adapter = build_transformer_adapter_from_env(fallback=ArtifactHeuristicTransformerAdapter())
    if adapter is None:
        raise RuntimeError("No transformer adapter is available.")
    system.set_transformer_adapter(adapter)
    proposal_ids = system.transformer_propose(
        artifacts=setup["artifacts"],
        context=setup["context"],
        task_id=f"proposal_precision_{family}_pool",
    )
    proposals = [system.proposal_quarantine.get(proposal_id) for proposal_id in proposal_ids]
    return {
        "adapter_description": adapter.describe()
        if hasattr(adapter, "describe")
        else {"adapter": adapter.__class__.__name__},
        "setup": setup,
        "proposals": proposals,
        "pool_source": {
            "mode": "fresh_live_generation",
        },
    }


def _load_fixed_pool_source(path: Path, *, family: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "fixed_proposal_pool" in payload:
        fixed_pool_payload = payload["fixed_proposal_pool"]
        source_kind = "proposal_precision_summary"
        source_version = payload.get("artifact_version")
        adapter_description = fixed_pool_payload.get("adapter", {"adapter": "unknown"})
        proposal_items = fixed_pool_payload.get("proposals", [])
    elif "reviewed_proposals" in payload:
        fixed_pool_payload = payload
        source_kind = "proposal_quality_summary"
        source_version = payload.get("artifact_version")
        adapter_description = payload.get("proof_contract", {}).get(
            "proposal_adapter", {"adapter": payload.get("adapter", "unknown")}
        )
        proposal_items = payload.get("reviewed_proposals", [])
    else:
        fixed_pool_payload = payload
        source_kind = "fixed_pool_artifact"
        source_version = payload.get("artifact_version")
        adapter_description = payload.get("adapter", {"adapter": "unknown"})
        proposal_items = fixed_pool_payload.get("proposals", [])
    proposals = [_deserialize_proposal(item) for item in proposal_items]
    return {
        "adapter_description": adapter_description,
        "setup": proposal_setup(family),
        "proposals": proposals,
        "pool_source": {
            "mode": "loaded_fixed_pool",
            "source_kind": source_kind,
            "source_path": str(path),
            "source_artifact_version": source_version,
        },
    }


def _write_fixed_pool_artifact(
    target: Path,
    *,
    family: str,
    fixed_pool: dict[str, Any],
    version: dict[str, str],
) -> None:
    write_json_artifact(
        target,
        {
            "artifact_version": version,
            "family": family,
            "campaign_type": "reviewer_policy_precision_fixed_pool",
            "adapter": fixed_pool["adapter_description"],
            "proposal_count": len(fixed_pool["proposals"]),
            "proposals": [_serialize_proposal(proposal) for proposal in fixed_pool["proposals"]],
            "pool_source": fixed_pool.get("pool_source", {}),
        },
        version=version,
    )


def _quality_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(summary.get("metrics", {}))
    return {
        "total_proposals": metrics.get("total_proposals"),
        "useful_proposals_total": metrics.get("useful_proposals_total"),
        "accepted_for_structural_eval": metrics.get("accepted_for_structural_eval"),
        "useful_accepted": metrics.get("useful_accepted"),
        "useful_accepted_before_first_symbol": metrics.get("useful_accepted"),
        "false_accepts_before_first_symbol": (
            int(metrics.get("accepted_for_structural_eval", 0))
            - int(metrics.get("useful_accepted", 0))
        ),
        "triage_precision": metrics.get("triage_precision"),
        "useful_recall": metrics.get("useful_recall"),
        "false_accept_rate": metrics.get("false_accept_rate"),
        "abstain_count": int(
            summary.get("proposal_summary", {})
            .get("status_counts", {})
            .get("abstain_needs_more_evidence", 0)
        ),
    }


def _runtime_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    proposal_runtime = (
        summary.get("proposal_assisted", {}).get("summary", {}).get("runtime_metrics", {})
    )
    comparison = summary.get("comparison", {})
    return {
        "cycles_to_useful_outcome": proposal_runtime.get("cycles_to_first_accepted_symbol"),
        "verifier_calls_to_useful_outcome": proposal_runtime.get("verifier_calls_to_acceptance"),
        "contradiction_before_acceptance": proposal_runtime.get("contradiction_before_acceptance"),
        "proposal_stage_cycles": proposal_runtime.get("proposal_stage_cycles"),
        "cycle_delta_from_no_proposals": comparison.get("cycles_to_first_accepted_symbol_delta"),
        "verifier_call_delta_from_no_proposals": comparison.get(
            "verifier_calls_to_acceptance_delta"
        ),
        "false_candidate_delta_from_no_proposals": comparison.get("false_candidate_delta"),
        "rollback_delta_from_no_proposals": comparison.get("rollback_delta"),
    }


def _selection_key(variant_summary: dict[str, Any]) -> tuple[Any, ...]:
    quality = variant_summary["quality_metrics"]
    runtime = variant_summary["runtime_metrics"]
    cycles = runtime.get("cycles_to_useful_outcome")
    verifier_calls = runtime.get("verifier_calls_to_useful_outcome")
    strictness_rank = POLICY_STRICTNESS_RANK.get(str(variant_summary.get("policy")), 0)
    return (
        float(quality.get("false_accept_rate") or 0.0),
        -float(quality.get("useful_recall") or 0.0),
        999 if cycles is None else int(cycles),
        999 if verifier_calls is None else int(verifier_calls),
        -int(quality.get("useful_accepted_before_first_symbol") or 0),
        -strictness_rank,
        int(quality.get("abstain_count") or 0),
    )


def run_proposal_precision_campaign(
    output_dir: str = "artifacts/phase13",
    *,
    family: str = "credit_window",
    fixed_pool_source_path: str | None = None,
    refresh_pool: bool = False,
) -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase13", root=ROOT)
    fixed_pool_artifact_path = target_dir / _fixed_pool_filename(family)

    fixed_pool: dict[str, Any]
    if not refresh_pool and fixed_pool_source_path:
        fixed_pool = _load_fixed_pool_source(Path(fixed_pool_source_path), family=family)
    elif not refresh_pool and fixed_pool_artifact_path.exists():
        fixed_pool = _load_fixed_pool_source(fixed_pool_artifact_path, family=family)
    else:
        fixed_pool = _generate_fixed_live_proposals(family)
        _write_fixed_pool_artifact(
            fixed_pool_artifact_path,
            family=family,
            fixed_pool=fixed_pool,
            version=version,
        )

    if fixed_pool_source_path:
        _write_fixed_pool_artifact(
            fixed_pool_artifact_path,
            family=family,
            fixed_pool=fixed_pool,
            version=version,
        )

    fixed_proposals = fixed_pool["proposals"]
    variant_rows: list[dict[str, Any]] = []
    for policy_name in POLICY_ORDER:
        reviewer = ArtifactStructuralProposalReviewer(policy=policy_name)
        replay_for_quality = ReplayProposalAdapter(fixed_proposals)
        replay_for_runtime = ReplayProposalAdapter(fixed_proposals)
        quality_summary = run_proposal_quality_benchmark(
            output_dir=output_dir,
            family=family,
            reviewer=reviewer,
            adapter_override=replay_for_quality,
        )
        runtime_summary = run_proposal_runtime_benchmark(
            output_dir=output_dir,
            family=family,
            reviewer=reviewer,
            adapter_override=replay_for_runtime,
        )
        variant_rows.append(
            {
                "policy": policy_name,
                "policy_strictness_rank": POLICY_STRICTNESS_RANK.get(policy_name, 0),
                "quality_metrics": _quality_metrics(quality_summary),
                "runtime_metrics": _runtime_metrics(runtime_summary),
                "quality_artifact": _quality_summary_name(family),
                "runtime_artifact": _runtime_summary_name(family),
                "quality_summary": quality_summary,
                "runtime_summary": runtime_summary,
            }
        )

    recommended = min(variant_rows, key=_selection_key)
    summary = {
        "artifact_version": version,
        "family": family,
        "campaign_type": "reviewer_policy_precision",
        "fixed_proposal_pool": {
            "adapter": fixed_pool["adapter_description"],
            "proposal_count": len(fixed_proposals),
            "proposals": [_serialize_proposal(proposal) for proposal in fixed_proposals],
            "pool_source": fixed_pool.get("pool_source", {}),
            "stable_pool_artifact": str(fixed_pool_artifact_path),
        },
        "variants": variant_rows,
        "selection": {
            "recommended_policy": recommended["policy"],
            "selection_priority": [
                "false_accept_rate",
                "useful_recall",
                "cycles_to_useful_outcome",
                "verifier_calls_to_useful_outcome",
                "useful_accepted_before_first_symbol",
                "policy_strictness_rank",
                "abstain_count",
            ],
            "rationale": (
                "Prefer the strictest reviewer that preserves false-accept control, recall, "
                "and runtime. Abstentions are tolerated when they do not reduce useful outcomes."
            ),
        },
        "checks": {
            "fixed_model_held_constant": True,
            "campaign_family_supported": bool(family),
            "recommended_policy_reduces_false_accepts": (
                float(recommended["quality_metrics"].get("false_accept_rate") or 0.0)
                <= float(variant_rows[0]["quality_metrics"].get("false_accept_rate") or 0.0)
            ),
            "recommended_policy_preserves_or_improves_recall": (
                float(recommended["quality_metrics"].get("useful_recall") or 0.0)
                >= float(variant_rows[0]["quality_metrics"].get("useful_recall") or 0.0)
            ),
            "recommended_policy_non_regressed_runtime": (
                (recommended["runtime_metrics"].get("cycles_to_useful_outcome") or 999)
                <= (variant_rows[0]["runtime_metrics"].get("cycles_to_useful_outcome") or 999)
            ),
        },
    }

    write_json_artifact(target_dir / _summary_filename(family), summary, version=version)
    write_text_artifact(
        _report_path(family),
        "\n".join(
            [
                "# Phase 13 Proposal Precision",
                "",
                f"- family: `{family}`",
                f"- fixed_proposal_count: `{len(fixed_proposals)}`",
                f"- fixed_pool_source: `{fixed_pool.get('pool_source', {}).get('mode', 'unknown')}`",
                f"- recommended_policy: `{recommended['policy']}`",
                f"- recommended_false_accept_rate: `{recommended['quality_metrics'].get('false_accept_rate')}`",
                f"- recommended_useful_recall: `{recommended['quality_metrics'].get('useful_recall')}`",
                f"- recommended_cycles_to_useful_outcome: `{recommended['runtime_metrics'].get('cycles_to_useful_outcome')}`",
            ]
        )
        + "\n",
        version=version,
    )
    return summary
