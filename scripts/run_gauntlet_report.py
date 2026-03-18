"""Generate a phase-7 gauntlet proof report from raw JSON artifacts only."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact

GAUNTLET_PATH = ROOT / "artifacts" / "phase7" / "gauntlet_summary.json"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary(raw: dict[str, Any], version: dict[str, str]) -> dict[str, Any]:
    metrics = dict(raw.get("summary_metrics", {}))
    checks = dict(raw.get("checks", {}))
    baseline_superiority = dict(metrics.get("baseline_superiority", {}))
    rows = list(raw.get("rows", []))

    wins: list[str] = []
    failures: list[str] = []
    unproven: list[str] = []

    if checks.get("ladder_a_positive_targets", 0) >= 2:
        wins.append("Ladder A now has two verifier-passing positive remap targets.")
    else:
        failures.append("Ladder A still lacks two verifier-passing positive remap targets.")

    if checks.get("ladder_b_positive_targets", 0) >= 2:
        wins.append("Ladder B now has two verifier-passing positive remap targets.")
    else:
        failures.append("Ladder B still lacks two verifier-passing positive remap targets.")

    if (
        checks.get("ladder_a_negative_blocks", 0) >= 1
        and checks.get("ladder_b_negative_blocks", 0) >= 1
    ):
        wins.append("Both ladders block at least one negative-transfer case.")
    else:
        failures.append("At least one ladder still lacks a blocked negative-transfer case.")

    if checks.get("cross_ladder_blocks", 0) >= 2:
        wins.append("Cross-ladder misuse is blocked in two explicit verifier-visible cases.")
    else:
        failures.append("Cross-ladder blocking is still below the required two cases.")

    if float(metrics.get("live_proposal_cycle_reduction_median", 0.0)) >= 0.25:
        wins.append("The live proposal layer preserves a median 25 percent cycle reduction.")
    else:
        failures.append(
            "The live proposal layer no longer preserves the required median cycle reduction."
        )

    if float(baseline_superiority.get("densn_positive_transfer_pass_rate", 0.0)) > float(
        baseline_superiority.get("model_baseline_transfer_pass_rate", 0.0)
    ):
        wins.append(
            "DENSN beats the strongest live model baselines on verifier-backed positive transfer rate."
        )
    else:
        failures.append(
            "DENSN does not currently beat the strongest live model baselines on transfer pass rate."
        )

    if float(baseline_superiority.get("densn_mean_verifier_calls_to_acceptance", 999.0)) <= float(
        baseline_superiority.get("model_baseline_mean_verifier_calls_to_acceptance", 0.0)
    ):
        wins.append(
            "DENSN is non-inferior on verifier calls to acceptance against the live model baselines."
        )
    else:
        failures.append("DENSN currently uses more verifier calls than the live model baselines.")

    if float(baseline_superiority.get("densn_mean_contradiction_gain", 0.0)) > float(
        baseline_superiority.get("model_baseline_mean_contradiction_gain", 0.0)
    ):
        wins.append("DENSN wins on contradiction reduction during transfer.")
    else:
        failures.append("DENSN does not currently win on contradiction reduction during transfer.")

    if float(metrics.get("accepted_interface_non_constant_rate", 0.0)) >= 0.75:
        wins.append(
            "Accepted abstractions remain predominantly non-constant at the interface level."
        )
    else:
        failures.append("Accepted abstraction interfaces are too often constant.")

    if float(metrics.get("verifier_agreement_rate", 0.0)) < 1.0:
        unproven.append(
            "Secondary-verifier agreement is reported but not yet clean; disagreement remains a live contradiction source."
        )

    if raw.get("artifact_version", {}).get("git_sha") == "nogit":
        unproven.append(
            "Artifacts are versioned, but the workspace is not a Git repo, so git_sha is a fallback marker rather than a real commit."
        )

    unproven.append("Pathway A compression is still not part of the headline proof bundle.")
    model_rows = [
        row
        for row in rows
        if str(row.get("system", "")).startswith("live_model")
        and row.get("case_kind") == "baseline_transfer"
    ]
    ladder_a_targets = {
        row.get("target_family") for row in model_rows if row.get("family") == "protocol_guard"
    }
    ladder_b_targets = {
        row.get("target_family") for row in model_rows if row.get("family") == "quorum_commit"
    }
    if len(ladder_a_targets) < 2 or len(ladder_b_targets) < 2:
        unproven.append(
            "The live model baselines are not yet exercised on two remap targets per ladder."
        )

    return {
        "artifact_version": version,
        "source_artifact": str(GAUNTLET_PATH),
        "headline_metrics": {
            "positive_targets_ladder_a": checks.get("ladder_a_positive_targets"),
            "positive_targets_ladder_b": checks.get("ladder_b_positive_targets"),
            "negative_blocks_total": checks.get("ladder_a_negative_blocks", 0)
            + checks.get("ladder_b_negative_blocks", 0),
            "cross_ladder_blocks": checks.get("cross_ladder_blocks"),
            "live_proposal_cycle_reduction_median": metrics.get(
                "live_proposal_cycle_reduction_median"
            ),
            "verifier_agreement_rate": metrics.get("verifier_agreement_rate"),
            "densn_positive_transfer_pass_rate": baseline_superiority.get(
                "densn_positive_transfer_pass_rate"
            ),
            "model_baseline_transfer_pass_rate": baseline_superiority.get(
                "model_baseline_transfer_pass_rate"
            ),
            "densn_mean_verifier_calls_to_acceptance": baseline_superiority.get(
                "densn_mean_verifier_calls_to_acceptance"
            ),
            "model_baseline_mean_verifier_calls_to_acceptance": baseline_superiority.get(
                "model_baseline_mean_verifier_calls_to_acceptance"
            ),
            "densn_mean_contradiction_gain": baseline_superiority.get(
                "densn_mean_contradiction_gain"
            ),
            "model_baseline_mean_contradiction_gain": baseline_superiority.get(
                "model_baseline_mean_contradiction_gain"
            ),
            "accepted_interface_non_constant_rate": metrics.get(
                "accepted_interface_non_constant_rate"
            ),
        },
        "wins": wins,
        "failures": failures,
        "unproven": unproven,
    }


def markdown_from_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Phase 7 Gauntlet Report",
        "",
        f"- Source artifact: `{summary['source_artifact']}`",
        f"- Artifact version: `{summary['artifact_version']['phase']}` / `{summary['artifact_version']['timestamp_utc']}` / `{summary['artifact_version']['git_sha']}`",
        "",
        "## Exact Wins",
    ]
    lines.extend(f"- {item}" for item in summary.get("wins", []))
    lines.append("")
    lines.append("## Exact Failures")
    if summary.get("failures"):
        lines.extend(f"- {item}" for item in summary["failures"])
    else:
        lines.append("- No failures were recorded in the current gauntlet artifact.")
    lines.append("")
    lines.append("## Still Unproven")
    lines.extend(f"- {item}" for item in summary.get("unproven", []))
    lines.append("")
    lines.append("## Headline Metrics")
    for key, value in summary.get("headline_metrics", {}).items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    version = artifact_version_info("phase7", root=ROOT)
    raw = load_json(GAUNTLET_PATH)
    summary = build_summary(raw, version)
    write_json_artifact(
        ROOT / "artifacts" / "phase7" / "gauntlet_proof_report.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase7_gauntlet_report.md",
        markdown_from_summary(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
