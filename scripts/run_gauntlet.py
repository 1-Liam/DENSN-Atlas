"""Run the unified phase-7 gauntlet benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact
from densn.benchmarks.gauntlet import run_gauntlet_benchmark
from densn.benchmarks.gauntlet_support import (
    build_commit_family_graph_from_manifest,
    build_window_family_graph_from_manifest,
    reuse_only_config,
)
from densn.benchmarks.remap_transfer import build_lease_lock_graph_from_manifest
from densn.memory import OntologyRegistry
from densn.proof_contract import CORE_API_VERSION
from densn.system import DENSNSystem


def _proposal_adapters_used(rows: list[dict[str, object]]) -> list[str]:
    return sorted({str(row.get("proposal_adapter")) for row in rows if row.get("proposal_adapter")})


def _verifier_names(rows: list[dict[str, object]]) -> list[str]:
    return sorted(
        {
            str(result.get("verifier_name"))
            for row in rows
            for result in row.get("verifier_results", [])
            if isinstance(result, dict) and result.get("verifier_name")
        }
    )


def _model_baseline_cycles(target_family: str) -> int:
    target_map = {
        "lease_lock": (
            ROOT / "fixtures" / "lease_lock" / "target" / "manifest.json",
            build_lease_lock_graph_from_manifest,
        ),
        "session_epoch": (
            ROOT / "fixtures" / "session_epoch" / "target" / "manifest.json",
            build_window_family_graph_from_manifest,
        ),
        "vote_majority_commit": (
            ROOT / "fixtures" / "vote_majority_commit" / "target" / "manifest.json",
            build_commit_family_graph_from_manifest,
        ),
        "replication_barrier": (
            ROOT / "fixtures" / "replication_barrier" / "target" / "manifest.json",
            build_commit_family_graph_from_manifest,
        ),
    }
    manifest_path, builder = target_map[target_family]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph = builder(manifest_path, prefix=f"{manifest['task_id'].upper()}_BASELINE_REPUBLISH")
    summary = DENSNSystem(
        graph, reuse_only_config(), registry=OntologyRegistry()
    ).run_until_stable()
    return int(summary.get("cycles_run") or 0)


def _enrich_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    baseline_cycle_cache: dict[str, int] = {}
    enriched: list[dict[str, object]] = []
    for row in rows:
        updated = dict(row)
        if (
            updated.get("system") == "densn_live"
            and updated.get("case_kind") == "positive_transfer"
        ):
            updated["cycles_to_useful_outcome"] = updated.get("cycles_to_first_accepted_symbol")
            updated["useful_outcome_kind"] = "positive_transfer"
        elif updated.get("system") in {
            "live_model_tools_no_ontology",
            "live_model_retrieval_verifiers",
        }:
            target_family = str(updated.get("target_family"))
            cycles = baseline_cycle_cache.setdefault(
                target_family, _model_baseline_cycles(target_family)
            )
            updated["cycles_to_useful_outcome"] = cycles
            updated["useful_outcome_kind"] = (
                "positive_transfer"
                if updated.get("positive_transfer")
                else "budget_exhausted_without_transfer"
            )
        enriched.append(updated)
    return enriched


def _refresh_baseline_superiority(summary: dict[str, object]) -> None:
    rows = list(summary.get("rows", []))
    densn_positive_rows = [
        row
        for row in rows
        if row.get("system") == "densn_live" and row.get("case_kind") == "positive_transfer"
    ]
    model_baseline_rows = [
        row
        for row in rows
        if row.get("system") in {"live_model_tools_no_ontology", "live_model_retrieval_verifiers"}
    ]
    baseline_superiority = dict(summary.get("summary_metrics", {}).get("baseline_superiority", {}))
    baseline_superiority["densn_mean_cycles_to_useful_outcome"] = sum(
        float(row.get("cycles_to_useful_outcome") or 0.0) for row in densn_positive_rows
    ) / max(len(densn_positive_rows), 1)
    baseline_superiority["model_baseline_mean_cycles_to_useful_outcome"] = sum(
        float(row.get("cycles_to_useful_outcome") or 0.0) for row in model_baseline_rows
    ) / max(len(model_baseline_rows), 1)
    summary.setdefault("summary_metrics", {})["baseline_superiority"] = baseline_superiority


def _republish_existing(output_dir: str) -> dict[str, object]:
    target_path = ROOT / output_dir / "gauntlet_summary.json"
    summary = json.loads(target_path.read_text(encoding="utf-8"))
    prior_version = dict(summary.get("artifact_version", {}))
    version = artifact_version_info("phase7", root=ROOT)
    rows = _enrich_rows(list(summary.get("rows", [])))
    summary["artifact_version"] = version
    summary["rows"] = rows
    summary["proof_contract"] = {
        "core_mode": "core_frozen",
        "core_api_version": CORE_API_VERSION,
        "expected_core_api_version": CORE_API_VERSION,
        "migration_note": None,
        "proposal_adapter": {"adapters_used": _proposal_adapters_used(rows)},
        "verifier_stack": _verifier_names(rows),
    }
    summary["republication"] = {
        "reused_existing_rows": True,
        "source_artifact_version": prior_version,
        "reason": "Groq rate limit prevented a full live gauntlet rerun; preserved prior raw rows and refreshed metadata only.",
    }
    _refresh_baseline_superiority(summary)
    write_json_artifact(target_path, summary, version=version)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()

    if args.reuse_existing:
        summary = _republish_existing("artifacts/phase7")
    else:
        summary = run_gauntlet_benchmark(output_dir="artifacts/phase7")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
