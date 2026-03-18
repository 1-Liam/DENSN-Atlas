"""Verify the current proof outputs against the packaged reproducibility expectations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def main() -> None:
    version = artifact_version_info("phase12", root=ROOT)
    expected = _load_json(ROOT / "repro" / "expected_metrics.json")
    repro_manifest = _load_json(ROOT / "artifacts" / "phase12" / "repro_kit_manifest.json")
    final_bundle = _load_json(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json")
    proof_manifest = _load_json(ROOT / "artifacts" / "phase10" / "proof_manifest.json")

    expected_checks = expected.get("headline_checks", {})
    actual_checks = final_bundle.get("checks", {})
    expected_pathway_b = expected.get("pathway_b", {}).get("baseline_superiority", {})
    actual_pathway_b = final_bundle.get("pathway_b_proof", {}).get("baseline_superiority", {})
    expected_live = expected.get("live_model", {})
    actual_live = final_bundle.get("live_model_contribution", {})

    checks = {
        "headline_checks_match": expected_checks == actual_checks,
        "transfer_pass_rate_match": _number(
            actual_pathway_b.get("densn_positive_transfer_pass_rate")
        )
        == _number(expected_pathway_b.get("densn_positive_transfer_pass_rate")),
        "pathway_a_compression_non_regressed": _number(
            final_bundle.get("pathway_a_proof", {}).get("compression_gain")
        )
        >= _number(expected.get("pathway_a", {}).get("compression_gain")),
        "live_false_accept_non_regressed": _number(
            actual_live.get("false_accept_rate"), default=1.0
        )
        <= _number(expected_live.get("false_accept_rate"), default=1.0),
        "fixture_hash_count_match": len(proof_manifest.get("fixture_hashes", []))
        == int(repro_manifest.get("fixture_hash_count", -1)),
        "verifier_hash_count_match": len(proof_manifest.get("verifier_manifest", []))
        == int(repro_manifest.get("verifier_hash_count", -1)),
    }

    summary = {
        "artifact_version": version,
        "expected_metrics_path": "repro/expected_metrics.json",
        "final_bundle_path": "artifacts/phase11/final_proof_bundle.json",
        "checks": checks,
        "verification_passed": all(checks.values()),
        "actual_checks": actual_checks,
        "expected_checks": expected_checks,
        "actual_live_model": actual_live,
        "actual_pathway_b": actual_pathway_b,
    }
    write_json_artifact(
        ROOT / "artifacts" / "phase12" / "repro_verification_summary.json", summary, version=version
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
