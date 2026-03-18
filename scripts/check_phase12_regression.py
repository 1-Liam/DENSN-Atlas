"""Compare a fresh-live candidate bundle against the current canonical bundle."""

from __future__ import annotations

import argparse
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


def _number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _write_report(summary: dict[str, Any], version: dict[str, str]) -> None:
    lines = [
        "# Phase 12 Fresh Live Regression",
        "",
        f"- regression_passed: `{summary.get('regression_passed')}`",
        f"- candidate_available: `{summary.get('candidate_available')}`",
    ]
    blocker = summary.get("blocker")
    if blocker:
        lines.append(f"- blocker_kind: `{blocker.get('kind')}`")
        lines.append(f"- blocker_reason: `{blocker.get('reason')}`")
    write_text_artifact(
        ROOT / "reports" / "phase12_fresh_live_report.md",
        "\n".join(lines) + "\n",
        version=version,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="artifacts/phase11/final_proof_bundle.json")
    parser.add_argument(
        "--candidate", default="artifacts/phase12/fresh_live_final_proof_bundle.json"
    )
    parser.add_argument("--output", default="artifacts/phase12/fresh_live_regression_check.json")
    args = parser.parse_args()

    version = artifact_version_info("phase12", root=ROOT)
    baseline_path = (ROOT / args.baseline).resolve()
    candidate_path = (ROOT / args.candidate).resolve()
    output_path = (ROOT / args.output).resolve()

    baseline = _load_json(baseline_path)
    summary: dict[str, Any] = {
        "artifact_version": version,
        "baseline_path": str(baseline_path),
        "candidate_path": str(candidate_path),
        "candidate_available": candidate_path.exists(),
        "regression_passed": False,
        "checks": {},
        "blocker": None,
    }

    if not candidate_path.exists():
        manifest_path = ROOT / "artifacts" / "phase12" / "fresh_live_run_manifest.json"
        manifest = _load_json(manifest_path) if manifest_path.exists() else {}
        summary["blocker"] = manifest.get("blocker") or {
            "kind": "candidate_missing",
            "reason": "No fresh live candidate bundle was produced.",
        }
        write_json_artifact(output_path, summary, version=version)
        _write_report(summary, version)
        print(json.dumps(summary, indent=2))
        return

    candidate = _load_json(candidate_path)
    baseline_superiority = baseline.get("pathway_b_proof", {}).get("baseline_superiority", {})
    candidate_superiority = candidate.get("pathway_b_proof", {}).get("baseline_superiority", {})
    baseline_live = baseline.get("live_model_contribution", {})
    candidate_live = candidate.get("live_model_contribution", {})

    checks = {
        "all_candidate_checks_true": all(
            bool(value) for value in candidate.get("checks", {}).values()
        ),
        "transfer_pass_rate_non_regressed": _number(
            candidate_superiority.get("densn_positive_transfer_pass_rate")
        )
        >= _number(baseline_superiority.get("densn_positive_transfer_pass_rate")),
        "verifier_calls_non_regressed": _number(
            candidate_superiority.get("densn_mean_verifier_calls_to_acceptance")
        )
        <= _number(
            baseline_superiority.get("densn_mean_verifier_calls_to_acceptance"), default=999.0
        ),
        "contradiction_gain_non_regressed": _number(
            candidate_superiority.get("densn_mean_contradiction_gain")
        )
        >= _number(baseline_superiority.get("densn_mean_contradiction_gain")),
        "cycles_to_useful_outcome_non_regressed": _number(
            candidate_superiority.get("densn_mean_cycles_to_useful_outcome")
        )
        <= _number(baseline_superiority.get("densn_mean_cycles_to_useful_outcome"), default=999.0),
        "live_proposal_gain_non_regressed": _number(candidate_live.get("median_cycle_reduction"))
        >= _number(baseline_live.get("median_cycle_reduction")),
        "false_accept_rate_non_regressed": _number(
            candidate_live.get("false_accept_rate"), default=1.0
        )
        <= _number(baseline_live.get("false_accept_rate"), default=1.0),
    }
    summary["checks"] = checks
    summary["regression_passed"] = all(checks.values())

    write_json_artifact(output_path, summary, version=version)
    _write_report(summary, version)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
