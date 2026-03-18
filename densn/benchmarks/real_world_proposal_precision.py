"""Deterministic reviewer replay gauntlet over fixed real-world proposal pools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from .proposal_precision import run_proposal_precision_campaign

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_DIR = ROOT / "artifacts" / "real_world"
FAMILY_POOL_SOURCES = {
    "etcd_raft_current_term": REAL_WORLD_DIR
    / "etcd_raft_current_term_proposal_quality_summary.json",
    "raft_rs_read_index_current_term": REAL_WORLD_DIR
    / "raft_rs_read_index_current_term_proposal_quality_summary.json",
    "redsync_mutex_extend": REAL_WORLD_DIR / "redsync_mutex_extend_proposal_quality_summary.json",
    "redislock_refresh": REAL_WORLD_DIR / "redislock_refresh_proposal_quality_summary.json",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _policy_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    false_rates = [float(row["quality_metrics"].get("false_accept_rate") or 0.0) for row in rows]
    recalls = [float(row["quality_metrics"].get("useful_recall") or 0.0) for row in rows]
    cycle_deltas = [
        int(row["runtime_metrics"].get("cycle_delta_from_no_proposals") or 0) for row in rows
    ]
    cycles = [int(row["runtime_metrics"].get("cycles_to_useful_outcome") or 999) for row in rows]
    return {
        "max_false_accept_rate": max(false_rates) if false_rates else None,
        "mean_false_accept_rate": sum(false_rates) / len(false_rates) if false_rates else None,
        "min_useful_recall": min(recalls) if recalls else None,
        "mean_useful_recall": sum(recalls) / len(recalls) if recalls else None,
        "min_cycle_delta": min(cycle_deltas) if cycle_deltas else None,
        "mean_cycle_delta": sum(cycle_deltas) / len(cycle_deltas) if cycle_deltas else None,
        "max_cycles_to_useful_outcome": max(cycles) if cycles else None,
    }


def _selection_key(policy_row: dict[str, Any]) -> tuple[Any, ...]:
    aggregate = policy_row["aggregate"]
    return (
        float(aggregate.get("max_false_accept_rate") or 0.0),
        -float(aggregate.get("min_useful_recall") or 0.0),
        -(int(aggregate.get("min_cycle_delta") or 0)),
        float(aggregate.get("mean_false_accept_rate") or 0.0),
        int(aggregate.get("max_cycles_to_useful_outcome") or 999),
    )


def run_real_world_proposal_precision_benchmark(
    output_dir: str = "artifacts/real_world",
) -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    family_summaries: dict[str, dict[str, Any]] = {}
    policy_rows: dict[str, list[dict[str, Any]]] = {}
    for family, source_path in FAMILY_POOL_SOURCES.items():
        summary = run_proposal_precision_campaign(
            output_dir=output_dir,
            family=family,
            fixed_pool_source_path=str(source_path),
            refresh_pool=False,
        )
        family_summaries[family] = summary
        for variant in summary.get("variants", []):
            policy_rows.setdefault(str(variant["policy"]), []).append(
                {
                    "family": family,
                    "quality_metrics": dict(variant.get("quality_metrics", {})),
                    "runtime_metrics": dict(variant.get("runtime_metrics", {})),
                }
            )

    aggregate_rows = []
    for policy_name, rows in policy_rows.items():
        aggregate_rows.append(
            {
                "policy": policy_name,
                "families": rows,
                "aggregate": _policy_aggregate(rows),
            }
        )
    recommended = min(aggregate_rows, key=_selection_key)

    summary = {
        "artifact_version": version,
        "domain": "real_world_proposal_precision",
        "fixed_pool_sources": {
            family: str(path.resolve()) for family, path in FAMILY_POOL_SOURCES.items()
        },
        "family_summaries": {
            family: {
                "pool_source": details.get("fixed_proposal_pool", {}).get("pool_source", {}),
                "recommended_policy": details.get("selection", {}).get("recommended_policy"),
                "variants": [
                    {
                        "policy": variant.get("policy"),
                        "quality_metrics": variant.get("quality_metrics"),
                        "runtime_metrics": variant.get("runtime_metrics"),
                    }
                    for variant in details.get("variants", [])
                ],
            }
            for family, details in family_summaries.items()
        },
        "policy_aggregate_rows": aggregate_rows,
        "selection": {
            "recommended_global_policy": recommended["policy"],
            "selection_priority": [
                "max_false_accept_rate",
                "min_useful_recall",
                "min_cycle_delta",
                "mean_false_accept_rate",
                "max_cycles_to_useful_outcome",
            ],
        },
        "checks": {
            "all_four_families_replayed": len(family_summaries) == 4,
            "no_live_generation_used": all(
                details.get("fixed_proposal_pool", {}).get("pool_source", {}).get("mode")
                == "loaded_fixed_pool"
                for details in family_summaries.values()
            ),
            "recommended_policy_preserves_cycle_gain": (
                int(recommended["aggregate"].get("min_cycle_delta") or 0) >= 1
            ),
            "recommended_policy_improves_false_accept_bound": (
                float(recommended["aggregate"].get("max_false_accept_rate") or 0.0) <= 0.1
            ),
        },
    }
    write_json_artifact(
        target_dir / "real_world_proposal_precision_summary.json", summary, version=version
    )
    return summary
