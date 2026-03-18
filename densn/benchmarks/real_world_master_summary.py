"""Raw-first master summary for the real-world external proof lane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_DIR = ROOT / "artifacts" / "real_world"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_real_world_master_summary(output_dir: str = "artifacts/real_world") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    gauntlet = _load_json(REAL_WORLD_DIR / "real_world_gauntlet_summary.json")
    proposal_assist = _load_json(REAL_WORLD_DIR / "real_world_proposal_assist_summary.json")

    source_families = list(gauntlet.get("source_families", []))
    positive_rows = list(gauntlet.get("positive_transfer_rows", []))
    negative_rows = list(gauntlet.get("cross_mechanism_negative_rows", []))
    quality_rows = list(proposal_assist.get("quality_rows", []))
    runtime_rows = list(proposal_assist.get("runtime_rows", []))

    summary = {
        "artifact_version": version,
        "domain": "real_world_master_summary",
        "source_families": source_families,
        "positive_transfer_rows": positive_rows,
        "cross_mechanism_negative_rows": negative_rows,
        "proposal_quality_rows": quality_rows,
        "proposal_runtime_rows": runtime_rows,
        "supporting_artifacts": {
            "gauntlet": str((REAL_WORLD_DIR / "real_world_gauntlet_summary.json").resolve()),
            "proposal_assist": str(
                (REAL_WORLD_DIR / "real_world_proposal_assist_summary.json").resolve()
            ),
        },
        "metrics": {
            "external_family_count": len(source_families),
            "positive_transfer_count": sum(
                1 for row in positive_rows if row.get("positive_transfer")
            ),
            "cross_mechanism_block_count": sum(1 for row in negative_rows if row.get("blocked")),
            "proposal_assist_family_count": len(quality_rows),
            "median_cycle_delta": proposal_assist.get("metrics", {}).get("median_cycle_delta"),
            "max_false_accept_rate": proposal_assist.get("metrics", {}).get(
                "max_false_accept_rate"
            ),
            "all_ontology_mutation_blocked": proposal_assist.get("metrics", {}).get(
                "all_ontology_mutation_blocked"
            ),
            "mean_contradiction_before_acceptance": proposal_assist.get("metrics", {}).get(
                "mean_contradiction_before_acceptance"
            ),
            "positive_transfer_contradiction_gain_sum": gauntlet.get("metrics", {}).get(
                "positive_transfer_contradiction_gain_sum"
            ),
        },
        "checks": {
            "all_external_source_solves_pass": bool(
                gauntlet.get("checks", {}).get("all_external_source_solves_pass")
            ),
            "within_mechanism_positive_transfers_pass": bool(
                gauntlet.get("checks", {}).get("within_mechanism_positive_transfers_pass")
            ),
            "cross_mechanism_negative_cases_blocked": bool(
                gauntlet.get("checks", {}).get("cross_mechanism_negative_cases_blocked")
            ),
            "live_proposal_gain_on_all_families": bool(
                proposal_assist.get("checks", {}).get("all_runtime_rows_show_gain")
            ),
            "proposal_quarantine_intact": bool(
                proposal_assist.get("checks", {}).get("all_quarantine_checks_hold")
            ),
        },
    }
    write_json_artifact(target_dir / "real_world_master_summary.json", summary, version=version)
    return summary
