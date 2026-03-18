"""Package the narrow formal-systems wedge claim against the frozen proof artifacts."""

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


def _report_markdown(summary: dict[str, Any]) -> str:
    checks = summary.get("checks", {})
    return (
        "\n".join(
            [
                "# Phase 12 Wedge",
                "",
                f"- wedge_ready: `{checks.get('wedge_ready')}`",
                f"- canonical_proof_intact: `{checks.get('canonical_proof_intact')}`",
                f"- reproducibility_verified: `{checks.get('reproducibility_verified')}`",
                f"- external_wedge_family_solved: `{checks.get('external_wedge_family_solved')}`",
                f"- live_model_baseline_beaten: `{checks.get('live_model_baseline_beaten')}`",
                "",
                f"- product_statement: `{summary.get('product_statement')}`",
            ]
        )
        + "\n"
    )


def main() -> None:
    version = artifact_version_info("phase12", root=ROOT)
    final_bundle = _load_json(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json")
    proof_manifest = _load_json(ROOT / "artifacts" / "phase10" / "proof_manifest.json")
    repro_summary = _load_json(ROOT / "artifacts" / "phase12" / "repro_verification_summary.json")
    credit_window = _load_json(ROOT / "artifacts" / "phase12" / "credit_window_summary.json")
    demo = _load_json(ROOT / "artifacts" / "phase12" / "decisive_demo_summary.json")

    summary = {
        "artifact_version": version,
        "product_statement": "Verifier-backed abstraction invention for formal systems.",
        "source_artifacts": {
            "final_proof_bundle": str(
                (ROOT / "artifacts" / "phase11" / "final_proof_bundle.json").resolve()
            ),
            "proof_manifest": str(
                (ROOT / "artifacts" / "phase10" / "proof_manifest.json").resolve()
            ),
            "repro_verification_summary": str(
                (ROOT / "artifacts" / "phase12" / "repro_verification_summary.json").resolve()
            ),
            "credit_window_summary": str(
                (ROOT / "artifacts" / "phase12" / "credit_window_summary.json").resolve()
            ),
            "decisive_demo_summary": str(
                (ROOT / "artifacts" / "phase12" / "decisive_demo_summary.json").resolve()
            ),
        },
        "input_contract": [
            "natural-language spec",
            "formal rules or formal spec",
            "traces",
            "failing tests",
            "logs",
            "counterexamples",
        ],
        "output_contract": [
            "missing invariant or hidden state",
            "reusable remapped abstraction when applicable",
            "verifier-backed explanation",
            "explicit non-transfer reason when blocked",
        ],
        "headline_proof": {
            "pathway_b": final_bundle.get("pathway_b_proof", {}),
            "pathway_a": final_bundle.get("pathway_a_proof", {}),
            "live_model_contribution": final_bundle.get("live_model_contribution", {}),
            "verifier_reliability": final_bundle.get("verifier_reliability", {}),
        },
        "external_wedge_family": {
            "family": "credit_window",
            "accepted_symbol": credit_window.get("accepted_record", {}).get("semantic_label"),
            "accepted_interface_non_constant": credit_window.get("checks", {}).get(
                "accepted_interface_non_constant"
            ),
            "heldout_reuse_success": credit_window.get("checks", {}).get("heldout_reuse_success"),
            "negative_transfer_blocked": credit_window.get("checks", {}).get(
                "negative_transfer_blocked"
            ),
            "live_model_baseline_beaten": credit_window.get("checks", {}).get(
                "live_model_baseline_beaten"
            ),
        },
        "frozen_core": {
            "core_frozen": proof_manifest.get("core_frozen"),
            "git_sha": proof_manifest.get("git_sha"),
            "model_backend_manifest": proof_manifest.get("model_backend_manifest"),
        },
        "demo_ready": {
            "family": demo.get("family"),
            "invention_verified": demo.get("checks", {}).get("invention_verified"),
            "positive_transfer_verified": demo.get("checks", {}).get("positive_transfer_verified"),
            "negative_transfer_blocked": demo.get("checks", {}).get("negative_transfer_blocked"),
            "baseline_beaten": demo.get("checks", {}).get("baseline_beaten"),
        },
        "checks": {
            "canonical_proof_intact": all(final_bundle.get("checks", {}).values()),
            "reproducibility_verified": bool(repro_summary.get("verification_passed")),
            "external_wedge_family_solved": bool(
                credit_window.get("checks", {}).get("accepted_symbol")
                and credit_window.get("checks", {}).get("heldout_reuse_success")
                and credit_window.get("checks", {}).get("negative_transfer_blocked")
            ),
            "live_model_baseline_beaten": bool(
                credit_window.get("checks", {}).get("live_model_baseline_beaten")
            ),
        },
    }
    summary["checks"]["wedge_ready"] = all(summary["checks"].values())

    write_json_artifact(
        ROOT / "artifacts" / "phase12" / "wedge_eval_summary.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase12_wedge_report.md",
        _report_markdown(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
