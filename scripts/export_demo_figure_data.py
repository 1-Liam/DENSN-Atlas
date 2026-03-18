"""Export compact figure data for the Phase 12 decisive demo."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _figure_plan(summary: dict[str, Any]) -> str:
    return (
        "\n".join(
            [
                "# Phase 12 Figure Plan",
                "",
                "## Figure 1: Contradiction to Acceptance",
                "",
                "- plot train-cycle `psi` from the credit-window telemetry",
                "- annotate the accepted abstraction event at the final zero-tension cycle",
                "",
                "## Figure 2: Learned Interface",
                "",
                "- table or heatmap of the accepted interface truth table preview",
                "- highlight that the interface is conditional, not constant",
                "",
                "## Figure 3: Transfer and Blocking",
                "",
                "- bars for baseline vs transferred `final_psi` on the held-out case",
                "- separate bar or callout for the blocked negative-transfer case",
                "",
                "## Figure 4: Baseline Contrast",
                "",
                "- show live model baseline `final_psi` and verifier failure reason",
                "- contrast with DENSN contradiction gain on the same family",
                "",
                f"- source_demo_family: `{summary.get('family')}`",
            ]
        )
        + "\n"
    )


def main() -> None:
    version = artifact_version_info("phase12", root=ROOT)
    demo = _load_json(ROOT / "artifacts" / "phase12" / "decisive_demo_summary.json")
    credit_window = _load_json(ROOT / "artifacts" / "phase12" / "credit_window_summary.json")
    telemetry_path = Path(
        str(credit_window.get("artifact_files", {}).get("credit_window_train_telemetry", ""))
    )
    telemetry_rows = _load_jsonl(telemetry_path)

    cycle_rows = [
        {
            "cycle": row.get("cycle"),
            "psi": row.get("psi"),
            "q": row.get("q"),
            "event_type": row.get("event_type"),
        }
        for row in telemetry_rows
        if row.get("event_type") == "cycle"
    ]

    transfer = demo.get("positive_transfer", {})
    blocked = demo.get("blocked_transfer", {})
    baseline = demo.get("baseline_contrast", {})
    figure_data = {
        "artifact_version": version,
        "family": demo.get("family"),
        "cycle_trace": cycle_rows,
        "accepted_interface_truth_table_preview": demo.get("invention", {}).get(
            "interface_truth_table_preview", {}
        ),
        "transfer_bars": {
            "heldout_baseline_final_psi": transfer.get("baseline_final_psi"),
            "heldout_transfer_final_psi": transfer.get("transfer_final_psi"),
            "heldout_contradiction_gain": transfer.get("contradiction_gain"),
        },
        "blocked_transfer_bar": {
            "negative_transfer_baseline_final_psi": blocked.get("baseline_final_psi"),
            "negative_transfer_final_psi": blocked.get("transfer_final_psi"),
            "blocker_reason": blocked.get("blocker_reason"),
        },
        "baseline_contrast_bar": {
            "densn_final_psi": transfer.get("transfer_final_psi"),
            "model_baseline_final_psi": baseline.get("final_psi"),
            "model_baseline_failure_reason": baseline.get("failure_reason"),
        },
    }

    write_json_artifact(
        ROOT / "artifacts" / "phase12" / "decisive_demo_figure_data.json",
        figure_data,
        version=version,
    )
    write_text_artifact(
        ROOT / "reports" / "phase12_figure_plan.md",
        _figure_plan(demo),
        version=version,
    )
    print(json.dumps(figure_data, indent=2))


if __name__ == "__main__":
    main()
