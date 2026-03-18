"""Generate a phase-5 proof report from raw JSON artifacts only."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact

RAW_SOURCES = {
    "formal_protocol": ROOT / "artifacts" / "phase1" / "formal_summary.json",
    "quorum_commit": ROOT / "artifacts" / "phase3" / "quorum_summary.json",
    "protocol_quality": ROOT / "artifacts" / "phase2" / "proposal_quality_summary.json",
    "protocol_runtime": ROOT / "artifacts" / "phase2" / "proposal_runtime_summary.json",
    "quorum_quality": ROOT / "artifacts" / "phase4" / "quorum_proposal_quality_summary.json",
    "quorum_runtime": ROOT / "artifacts" / "phase4" / "quorum_proposal_runtime_summary.json",
    "transfer_matrix": ROOT / "artifacts" / "phase4" / "transfer_matrix_summary.json",
    "readiness": ROOT / "artifacts" / "readiness" / "core_integrity_audit.json",
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary(raw: dict[str, dict[str, Any]], version: dict[str, str]) -> dict[str, Any]:
    formal = raw["formal_protocol"]
    quorum = raw["quorum_commit"]
    protocol_runtime = raw["protocol_runtime"]
    quorum_runtime = raw["quorum_runtime"]
    transfer_matrix = raw["transfer_matrix"]
    readiness = raw["readiness"]
    quorum_quality = raw["quorum_quality"]

    wins: list[str] = []
    failures: list[str] = []

    if formal.get("train_summary", {}).get("final_psi") == 0.0:
        wins.append("protocol_guard still reaches zero final tension")
    else:
        failures.append("protocol_guard no longer reaches zero final tension")

    if quorum.get("accepted_interface_is_constant") is False:
        wins.append("quorum_commit still has a non-constant accepted interface")
    else:
        failures.append("quorum_commit accepted interface is no longer non-constant")

    if protocol_runtime.get("comparison", {}).get("cycles_to_first_accepted_symbol_delta", 0) >= 1:
        wins.append("live protocol proposal path still improves cycles to first accepted symbol")
    else:
        failures.append("live protocol proposal path lost its cycle improvement")

    if quorum_runtime.get("comparison", {}).get("cycles_to_first_accepted_symbol_delta", 0) >= 1:
        wins.append("live quorum proposal path still improves cycles to first accepted symbol")
    else:
        failures.append("live quorum proposal path lost its cycle improvement")

    if transfer_matrix.get("checks", {}).get("cross_family_reuse_blocked"):
        wins.append("cross-family reuse is blocked in both current directions")
    else:
        failures.append("cross-family reuse is no longer blocked cleanly")

    if transfer_matrix.get("checks", {}).get("negative_transfer_verifier_blocked"):
        wins.append("negative transfer is blocked by the verifier")
    else:
        failures.append("negative transfer is no longer blocked by the verifier")

    if readiness.get("readiness", {}).get("proceed_recommended"):
        wins.append("core readiness audit still recommends proceeding")
    else:
        failures.append("core readiness audit no longer recommends proceeding")

    if quorum_quality.get("proposal_summary", {}).get("total", 0) <= 1:
        failures.append(
            "standalone live quorum proposal quality remains narrow compared with the in-loop runtime path"
        )

    return {
        "artifact_version": version,
        "sources": {name: str(path) for name, path in RAW_SOURCES.items()},
        "missing_sources": [name for name, path in RAW_SOURCES.items() if not path.exists()],
        "wins": wins,
        "failures": failures,
        "headline_metrics": {
            "protocol_final_psi": formal.get("train_summary", {}).get("final_psi"),
            "quorum_final_psi": quorum.get("train_summary", {}).get("final_psi"),
            "protocol_cycle_delta": protocol_runtime.get("comparison", {}).get(
                "cycles_to_first_accepted_symbol_delta"
            ),
            "quorum_cycle_delta": quorum_runtime.get("comparison", {}).get(
                "cycles_to_first_accepted_symbol_delta"
            ),
            "cross_family_blocked": transfer_matrix.get("checks", {}).get(
                "cross_family_reuse_blocked"
            ),
            "negative_transfer_blocked": transfer_matrix.get("checks", {}).get(
                "negative_transfer_verifier_blocked"
            ),
        },
        "raw_artifacts_consistent": not failures[:-1] if failures else True,
    }


def markdown_from_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Phase 5 Proof Report",
        "",
        f"- Artifact version: `{summary['artifact_version']['phase']}` / `{summary['artifact_version']['timestamp_utc']}` / `{summary['artifact_version']['git_sha']}`",
        "",
        "## Wins",
    ]
    lines.extend(f"- {item}" for item in summary.get("wins", []))
    lines.append("")
    lines.append("## Failures")
    if summary.get("failures"):
        lines.extend(f"- {item}" for item in summary["failures"])
    else:
        lines.append("- No failures recorded in the current raw artifact set.")
    lines.append("")
    lines.append("## Headline Metrics")
    for key, value in summary.get("headline_metrics", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Sources")
    for name, path in summary.get("sources", {}).items():
        lines.append(f"- {name}: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    version = artifact_version_info("phase5", root=ROOT)
    raw = {name: load_json(path) for name, path in RAW_SOURCES.items()}
    summary = build_summary(raw, version)

    output_dir = ROOT / "artifacts" / "phase5"
    write_json_artifact(output_dir / "phase5_proof_report.json", summary, version=version)
    write_text_artifact(
        ROOT / "reports" / "phase5_proof_report.md",
        markdown_from_summary(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
