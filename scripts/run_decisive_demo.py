"""Run the narrow Phase 12 decisive demo on the external credit-window wedge."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from densn.benchmarks.credit_window import run_credit_window_benchmark


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _truth_table_preview(record: dict[str, Any] | None) -> dict[str, bool]:
    if not record:
        return {}
    truth_table = record.get("interface_definition", {}).get("truth_table", {})
    preview_keys = sorted(truth_table.keys())[:4]
    return {key: bool(truth_table[key]) for key in preview_keys}


def _walkthrough_markdown(summary: dict[str, Any]) -> str:
    invention = summary.get("invention", {})
    transfer = summary.get("positive_transfer", {})
    blocked = summary.get("blocked_transfer", {})
    baseline = summary.get("baseline_contrast", {})
    checks = summary.get("checks", {})
    return (
        "\n".join(
            [
                "# Phase 12 Decisive Demo",
                "",
                f"- unseen_bundle_family: `{summary.get('family')}`",
                f"- invention_verified: `{checks.get('invention_verified')}`",
                f"- transfer_verified: `{checks.get('positive_transfer_verified')}`",
                f"- blocked_bad_transfer: `{checks.get('negative_transfer_blocked')}`",
                f"- baseline_beaten: `{checks.get('baseline_beaten')}`",
                "",
                "## Invention",
                "",
                f"- label: `{invention.get('semantic_label')}`",
                f"- cycles_to_acceptance: `{invention.get('cycles_to_first_accepted_symbol')}`",
                f"- final_psi: `{invention.get('final_psi')}`",
                f"- verifier_passed: `{invention.get('verifier_passed')}`",
                f"- interface_non_constant: `{invention.get('interface_non_constant')}`",
                "",
                "## Positive Transfer",
                "",
                f"- target_task: `{transfer.get('task_id')}`",
                f"- mapping_class: `{transfer.get('mapping_class')}`",
                f"- contradiction_gain: `{transfer.get('contradiction_gain')}`",
                f"- transfer_final_psi: `{transfer.get('transfer_final_psi')}`",
                f"- verifier_passed: `{transfer.get('verifier_passed')}`",
                "",
                "## Blocked Transfer",
                "",
                f"- target_task: `{blocked.get('task_id')}`",
                f"- blocker_reason: `{blocked.get('blocker_reason')}`",
                "",
                "## Baseline Contrast",
                "",
                f"- baseline_status: `{baseline.get('status')}`",
                f"- verifier_passed: `{baseline.get('verifier_passed')}`",
                f"- final_psi: `{baseline.get('final_psi')}`",
                f"- contradiction_gain: `{baseline.get('contradiction_gain')}`",
                f"- failure_reason: `{baseline.get('failure_reason')}`",
            ]
        )
        + "\n"
    )


def main() -> None:
    version = artifact_version_info("phase12", root=ROOT)
    final_bundle = _load_json(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json")
    credit_window = run_credit_window_benchmark(output_dir="artifacts/phase12")

    accepted_record = credit_window.get("accepted_record", {})
    transfer = (credit_window.get("transfer_results") or [{}])[0]
    reuse_applications = transfer.get("reuse_applications") or [{}]
    positive_mapping = reuse_applications[0] if reuse_applications else {}
    negative_transfer = credit_window.get("negative_transfer", {})
    negative_verification = negative_transfer.get("verification", {})
    baseline = credit_window.get("live_model_baseline", {})
    baseline_verification = baseline.get("verification", {})
    invention_verifications = accepted_record.get("verifications") or [{}]
    invention_verification = invention_verifications[0] if invention_verifications else {}

    summary = {
        "artifact_version": version,
        "family": "credit_window",
        "source_artifacts": {
            "phase11_final_proof_bundle": str(
                (ROOT / "artifacts" / "phase11" / "final_proof_bundle.json").resolve()
            ),
            "phase12_credit_window_summary": str(
                (ROOT / "artifacts" / "phase12" / "credit_window_summary.json").resolve()
            ),
            "phase12_credit_window_transfer_summary": str(
                (ROOT / "artifacts" / "phase12" / "credit_window_transfer_summary.json").resolve()
            ),
        },
        "ingested_bundle": {
            "manifest_path": credit_window.get("train_manifest_path"),
            "artifact_files": credit_window.get("artifact_files", {}),
        },
        "proposal_quarantine": {
            "zero_direct_ontology_mutation": bool(
                final_bundle.get("live_model_contribution", {}).get("zero_direct_ontology_mutation")
            ),
            "proposal_adapter": final_bundle.get("provenance", {}).get(
                "model_backend_manifest", {}
            ),
        },
        "invention": {
            "meta_symbol_id": credit_window.get("accepted_meta_symbol_id"),
            "semantic_label": accepted_record.get("semantic_label"),
            "cycles_to_first_accepted_symbol": credit_window.get("proof_contract", {})
            .get("runtime_metrics", {})
            .get("cycles_to_first_accepted_symbol"),
            "final_psi": credit_window.get("train_summary", {}).get("final_psi"),
            "verifier_passed": invention_verification.get("passed"),
            "interface_non_constant": credit_window.get("accepted_interface_is_constant") is False,
            "interface_truth_table_preview": _truth_table_preview(accepted_record),
            "bridge_audits": accepted_record.get("audits", []),
        },
        "positive_transfer": {
            "task_id": transfer.get("task_id"),
            "mapping_class": positive_mapping.get("mapping_class"),
            "mapping_confidence": positive_mapping.get("mapping_confidence"),
            "baseline_final_psi": transfer.get("baseline_summary", {}).get("final_psi"),
            "transfer_final_psi": transfer.get("summary", {}).get("final_psi"),
            "contradiction_gain": transfer.get("contradiction_gain"),
            "verifier_passed": transfer.get("verification", {}).get("passed"),
        },
        "blocked_transfer": {
            "task_id": negative_transfer.get("task_id"),
            "baseline_final_psi": negative_transfer.get("baseline_summary", {}).get("final_psi"),
            "transfer_final_psi": negative_transfer.get("summary", {}).get("final_psi"),
            "blocker_reason": (negative_verification.get("counterexample") or {}).get("reason"),
            "verifier_passed": negative_verification.get("passed"),
        },
        "baseline_contrast": {
            "status": baseline.get("status"),
            "label": (baseline.get("hypothesis") or {}).get("label"),
            "verifier_passed": baseline_verification.get("passed"),
            "final_psi": baseline.get("summary", {}).get("final_psi"),
            "contradiction_gain": baseline.get("contradiction_gain"),
            "failure_reason": (baseline_verification.get("counterexample") or {}).get("reason"),
        },
        "checks": {
            "invention_verified": bool(
                credit_window.get("checks", {}).get("accepted_symbol")
                and invention_verification.get("passed")
                and credit_window.get("train_summary", {}).get("final_psi") == 0.0
            ),
            "positive_transfer_verified": bool(
                credit_window.get("checks", {}).get("heldout_reuse_success")
                and transfer.get("verification", {}).get("passed")
            ),
            "negative_transfer_blocked": bool(
                credit_window.get("checks", {}).get("negative_transfer_blocked")
            ),
            "baseline_beaten": bool(
                credit_window.get("checks", {}).get("live_model_baseline_beaten")
            ),
            "proposal_quarantine_intact": bool(
                final_bundle.get("live_model_contribution", {}).get("zero_direct_ontology_mutation")
            ),
        },
    }

    write_json_artifact(
        ROOT / "artifacts" / "phase12" / "decisive_demo_summary.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase12_demo_walkthrough.md",
        _walkthrough_markdown(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
