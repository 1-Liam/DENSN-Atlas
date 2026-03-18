"""Build a raw verifier-agreement artifact from the phase-7 gauntlet."""

from __future__ import annotations

import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact
from densn.proof_contract import CORE_API_VERSION

GAUNTLET_PATH = ROOT / "artifacts" / "phase7" / "gauntlet_summary.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_disagreement(row: dict[str, Any]) -> dict[str, Any]:
    results = list(row.get("verifier_results", []))
    failing = [result for result in results if result.get("failed")]
    passing = [result for result in results if result.get("passed")]
    reasons = [
        result.get("counterexample", {}).get("reason")
        for result in failing
        if isinstance(result.get("counterexample"), dict)
    ]
    reasons = [reason for reason in reasons if reason]
    primary = results[0] if results else {}
    primary_name = str(primary.get("verifier_name", "none"))

    if not passing or not failing:
        return {
            "classification": "agreement",
            "resolved": True,
            "reason": None,
            "expanded_counterexamples": reasons,
        }
    if primary.get("status") == "verifier_error":
        return {
            "classification": "underspecified_artifact_bundle",
            "resolved": True,
            "reason": "verifier_error",
            "expanded_counterexamples": reasons,
        }
    if len(failing) >= 2:
        return {
            "classification": "true_structural_contradiction",
            "resolved": True,
            "reason": reasons[0] if reasons else primary.get("status"),
            "expanded_counterexamples": reasons,
        }
    if primary_name not in {"role_count_verifier", "trace_contract_verifier"}:
        return {
            "classification": "benign_verifier_surface_mismatch",
            "resolved": True,
            "reason": reasons[0] if reasons else primary.get("status"),
            "expanded_counterexamples": reasons,
        }
    return {
        "classification": "unresolved_disagreement",
        "resolved": False,
        "reason": reasons[0] if reasons else primary.get("status"),
        "expanded_counterexamples": reasons,
    }


def build_summary(raw: dict[str, Any], version: dict[str, str]) -> dict[str, Any]:
    rows = [
        row
        for row in raw.get("rows", [])
        if row.get("system") == "densn_live" and row.get("verifier_results")
    ]
    diagnostics: list[dict[str, Any]] = []
    pair_counter: Counter[str] = Counter()
    agreement_count = 0
    disagreement_count = 0
    resolved_disagreement_count = 0
    contradiction_added_count = 0

    family_counter: dict[str, Counter[str]] = {}

    for row in rows:
        results = list(row.get("verifier_results", []))
        outcome_set = {bool(result.get("passed")) for result in results}
        all_agree = len(outcome_set) == 1
        if all_agree:
            agreement_count += 1
        else:
            disagreement_count += 1
            contradiction_added_count += 1

        diagnostic = classify_disagreement(row)
        if not all_agree and diagnostic["resolved"]:
            resolved_disagreement_count += 1

        verifier_names = sorted(str(result.get("verifier_name")) for result in results)
        for left, right in combinations(verifier_names, 2):
            pair_counter[f"{left}__{right}"] += 1

        family = str(row.get("family"))
        family_counter.setdefault(family, Counter())[diagnostic["classification"]] += 1

        diagnostics.append(
            {
                "family": row.get("family"),
                "target_family": row.get("target_family"),
                "case_kind": row.get("case_kind"),
                "mapping_class": row.get("mapping_class"),
                "verifier_statuses": [
                    {
                        "verifier_name": result.get("verifier_name"),
                        "status": result.get("status"),
                        "passed": result.get("passed"),
                        "counterexample": result.get("counterexample"),
                    }
                    for result in results
                ],
                **diagnostic,
            }
        )

    total = max(len(rows), 1)
    agreement_rate = agreement_count / total
    disagreement_rate = disagreement_count / total
    disagreement_resolved_rate = (
        resolved_disagreement_count / disagreement_count if disagreement_count else 1.0
    )
    effective_agreement_quality = agreement_rate + disagreement_rate * disagreement_resolved_rate

    return {
        "artifact_version": version,
        "proof_contract": {
            "core_mode": raw.get("proof_contract", {}).get("core_mode", "core_frozen"),
            "core_api_version": raw.get("proof_contract", {}).get(
                "core_api_version", CORE_API_VERSION
            ),
            "expected_core_api_version": raw.get("proof_contract", {}).get(
                "expected_core_api_version",
                CORE_API_VERSION,
            ),
            "migration_note": raw.get("proof_contract", {}).get("migration_note"),
            "proposal_adapter": raw.get("proof_contract", {}).get("proposal_adapter"),
            "verifier_stack": raw.get("proof_contract", {}).get("verifier_stack", []),
        },
        "source_artifact": str(GAUNTLET_PATH),
        "agreement_rate": agreement_rate,
        "disagreement_rate": disagreement_rate,
        "disagreement_resolved_rate": disagreement_resolved_rate,
        "effective_agreement_quality": effective_agreement_quality,
        "unresolved_disagreement_count": disagreement_count - resolved_disagreement_count,
        "contradiction_added_from_disagreement_count": contradiction_added_count,
        "verifier_surface_pairs": dict(pair_counter),
        "family_diagnostics": {
            family: dict(counter) for family, counter in sorted(family_counter.items())
        },
        "diagnostic_rows": diagnostics,
    }


def markdown_from_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Verifier Agreement",
        "",
        f"- source_artifact: `{summary['source_artifact']}`",
        f"- agreement_rate: `{summary['agreement_rate']}`",
        f"- disagreement_rate: `{summary['disagreement_rate']}`",
        f"- disagreement_resolved_rate: `{summary['disagreement_resolved_rate']}`",
        f"- effective_agreement_quality: `{summary['effective_agreement_quality']}`",
        f"- unresolved_disagreement_count: `{summary['unresolved_disagreement_count']}`",
        f"- contradiction_added_from_disagreement_count: `{summary['contradiction_added_from_disagreement_count']}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    version = artifact_version_info("phase9", root=ROOT)
    raw = load_json(GAUNTLET_PATH)
    summary = build_summary(raw, version)
    write_json_artifact(
        ROOT / "artifacts" / "phase9" / "verifier_agreement_summary.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase9_verifier_agreement_report.md",
        markdown_from_summary(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
