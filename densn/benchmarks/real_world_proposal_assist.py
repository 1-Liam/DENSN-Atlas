"""Aggregate live proposal assistance on real-world external families."""

from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..proposal_review import ArtifactStructuralProposalReviewer
from .proposal_quality import run_proposal_quality_benchmark
from .proposal_runtime import run_proposal_runtime_benchmark

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_FAMILIES = [
    "etcd_raft_current_term",
    "raft_rs_read_index_current_term",
    "redsync_mutex_extend",
    "redislock_refresh",
]


def _quality_row(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(summary.get("metrics", {}))
    return {
        "family": summary.get("family"),
        "adapter": summary.get("adapter"),
        "total_proposals": metrics.get("total_proposals"),
        "accepted_for_structural_eval": metrics.get("accepted_for_structural_eval"),
        "triage_precision": metrics.get("triage_precision"),
        "useful_recall": metrics.get("useful_recall"),
        "false_accept_rate": metrics.get("false_accept_rate"),
        "ontology_mutated_directly": summary.get("ontology_mutated_directly"),
    }


def _runtime_row(summary: dict[str, Any]) -> dict[str, Any]:
    comparison = dict(summary.get("comparison", {}))
    proposal_assisted = dict(summary.get("proposal_assisted", {}))
    runtime_metrics = dict(proposal_assisted.get("summary", {}).get("runtime_metrics", {}))
    return {
        "family": summary.get("family"),
        "adapter": proposal_assisted.get("adapter"),
        "cycles_delta": comparison.get("cycles_to_first_accepted_symbol_delta"),
        "verifier_calls_delta": comparison.get("verifier_calls_to_acceptance_delta"),
        "false_candidate_delta": comparison.get("false_candidate_delta"),
        "rollback_delta": comparison.get("rollback_delta"),
        "proposal_stage_cycles": runtime_metrics.get("proposal_stage_cycles"),
        "accepted_proposal_count": runtime_metrics.get("accepted_proposal_count"),
        "contradiction_before_acceptance": runtime_metrics.get("contradiction_before_acceptance"),
    }


def run_real_world_proposal_assist_benchmark(
    output_dir: str = "artifacts/real_world",
    *,
    families: list[str] | None = None,
) -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    selected = list(families or REAL_WORLD_FAMILIES)
    quality_rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    reviewer = ArtifactStructuralProposalReviewer(policy="real_world_strict")

    for family in selected:
        quality_summary = run_proposal_quality_benchmark(
            output_dir=output_dir,
            family=family,
            reviewer=reviewer,
        )
        runtime_summary = run_proposal_runtime_benchmark(
            output_dir=output_dir,
            family=family,
            reviewer=reviewer,
        )
        quality_rows.append(_quality_row(quality_summary))
        runtime_rows.append(_runtime_row(runtime_summary))

    cycle_deltas = [
        int(row["cycles_delta"]) for row in runtime_rows if row.get("cycles_delta") is not None
    ]
    false_accept_rates = [
        float(row["false_accept_rate"])
        for row in quality_rows
        if row.get("false_accept_rate") is not None
    ]
    contradiction_values = [
        float(row["contradiction_before_acceptance"])
        for row in runtime_rows
        if row.get("contradiction_before_acceptance") is not None
    ]

    summary = {
        "artifact_version": version,
        "domain": "real_world_proposal_assist",
        "families": selected,
        "quality_rows": quality_rows,
        "runtime_rows": runtime_rows,
        "metrics": {
            "family_count": len(selected),
            "median_cycle_delta": median(cycle_deltas) if cycle_deltas else None,
            "max_false_accept_rate": max(false_accept_rates) if false_accept_rates else None,
            "all_false_accept_rates_zero": all(rate <= 0.0 for rate in false_accept_rates),
            "all_ontology_mutation_blocked": all(
                row.get("ontology_mutated_directly") is False for row in quality_rows
            ),
            "mean_contradiction_before_acceptance": (
                sum(contradiction_values) / len(contradiction_values)
                if contradiction_values
                else None
            ),
        },
        "checks": {
            "all_families_reported": len(quality_rows) == len(selected) == len(runtime_rows),
            "all_runtime_rows_show_gain": all(
                (row.get("cycles_delta") or 0) >= 1 for row in runtime_rows
            ),
            "all_quarantine_checks_hold": all(
                row.get("ontology_mutated_directly") is False for row in quality_rows
            ),
        },
    }
    write_json_artifact(
        target_dir / "real_world_proposal_assist_summary.json", summary, version=version
    )
    return summary
