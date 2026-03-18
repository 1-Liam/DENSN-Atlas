"""Assemble the final raw DENSN proof bundle."""

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
    "gauntlet": ROOT / "artifacts" / "phase7" / "gauntlet_summary.json",
    "pathway_a": ROOT / "artifacts" / "phase8" / "pathway_a_summary.json",
    "proposal_quality": ROOT / "artifacts" / "phase2" / "proposal_quality_summary.json",
    "proposal_precision": ROOT / "artifacts" / "phase13" / "proposal_precision_summary.json",
    "protocol_runtime": ROOT / "artifacts" / "phase2" / "proposal_runtime_summary.json",
    "quorum_runtime": ROOT / "artifacts" / "phase4" / "quorum_proposal_runtime_summary.json",
    "verifier_agreement": ROOT / "artifacts" / "phase9" / "verifier_agreement_summary.json",
    "proof_manifest": ROOT / "artifacts" / "phase10" / "proof_manifest.json",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def recommended_precision_variant(summary: dict[str, Any]) -> dict[str, Any]:
    recommended_policy = summary.get("selection", {}).get("recommended_policy")
    for variant in summary.get("variants", []):
        if variant.get("policy") == recommended_policy:
            return dict(variant)
    return {}


def build_summary(raw: dict[str, dict[str, Any]], version: dict[str, str]) -> dict[str, Any]:
    gauntlet = raw["gauntlet"]
    pathway_a = raw["pathway_a"]
    proposal_quality = raw["proposal_quality"]
    proposal_precision = raw["proposal_precision"]
    protocol_runtime = raw["protocol_runtime"]
    quorum_runtime = raw["quorum_runtime"]
    verifier_agreement = raw["verifier_agreement"]
    proof_manifest = raw["proof_manifest"]
    precision_variant = recommended_precision_variant(proposal_precision)
    precision_quality = precision_variant.get("quality_metrics", {})
    precision_runtime = precision_variant.get("runtime_metrics", {})
    precision_quality_summary = precision_variant.get("quality_summary", {})

    comparison = {
        "protocol_cycle_delta": protocol_runtime.get("comparison", {}).get(
            "cycles_to_first_accepted_symbol_delta"
        ),
        "quorum_cycle_delta": quorum_runtime.get("comparison", {}).get(
            "cycles_to_first_accepted_symbol_delta"
        ),
        "protocol_contradiction_before_acceptance_delta": (
            float(
                protocol_runtime.get("baseline", {})
                .get("summary", {})
                .get("runtime_metrics", {})
                .get("contradiction_before_acceptance")
                or 0.0
            )
            - float(
                protocol_runtime.get("proposal_assisted", {})
                .get("summary", {})
                .get("runtime_metrics", {})
                .get("contradiction_before_acceptance")
                or 0.0
            )
        ),
        "quorum_contradiction_before_acceptance_delta": (
            float(
                quorum_runtime.get("baseline", {})
                .get("summary", {})
                .get("runtime_metrics", {})
                .get("contradiction_before_acceptance")
                or 0.0
            )
            - float(
                quorum_runtime.get("proposal_assisted", {})
                .get("summary", {})
                .get("runtime_metrics", {})
                .get("contradiction_before_acceptance")
                or 0.0
            )
        ),
    }

    checks = {
        "pathway_b_non_regressed": bool(
            gauntlet.get("checks", {}).get("ladder_a_positive_targets", 0) >= 2
            and gauntlet.get("checks", {}).get("ladder_b_positive_targets", 0) >= 2
            and gauntlet.get("checks", {}).get("cross_ladder_blocks", 0) >= 2
        ),
        "pathway_a_real": bool(
            pathway_a.get("checks", {}).get("accepted_pathway_a_symbol")
            and pathway_a.get("checks", {}).get("downstream_cycles_reduction_positive")
            and pathway_a.get("checks", {}).get("no_pathway_a_ablation_positive")
        ),
        "verifier_reliability_operationalized": bool(
            verifier_agreement.get("unresolved_disagreement_count", 1) == 0
            and float(verifier_agreement.get("effective_agreement_quality", 0.0)) > 0.5
        ),
        "provenance_hardened": bool(
            proof_manifest.get("git_sha") not in {None, "", "nogit"}
            and proof_manifest.get("core_frozen") is True
        ),
        "proposal_quarantine_intact": (
            proposal_quality.get("ontology_mutated_directly") is False
            and precision_quality_summary.get("ontology_mutated_directly") is False
        ),
    }

    return {
        "artifact_version": version,
        "sources": {name: repo_relative(path) for name, path in RAW_SOURCES.items()},
        "pathway_b_proof": {
            "positive_remap_targets": {
                "ladder_a": gauntlet.get("checks", {}).get("ladder_a_positive_targets"),
                "ladder_b": gauntlet.get("checks", {}).get("ladder_b_positive_targets"),
            },
            "blocked_negative_transfer": {
                "ladder_a": gauntlet.get("checks", {}).get("ladder_a_negative_blocks"),
                "ladder_b": gauntlet.get("checks", {}).get("ladder_b_negative_blocks"),
            },
            "blocked_cross_ladder_misuse": gauntlet.get("checks", {}).get("cross_ladder_blocks"),
            "baseline_superiority": gauntlet.get("summary_metrics", {}).get("baseline_superiority"),
        },
        "pathway_a_proof": {
            "compression_gain": pathway_a.get("compression_gain"),
            "mdl_or_symbolic_tax_reduction": pathway_a.get("mdl_or_symbolic_tax_reduction"),
            "ontology_size_before_after": pathway_a.get("ontology_size_before_after"),
            "downstream_cycles_reduction": pathway_a.get("downstream_cycles_reduction"),
            "downstream_verifier_calls_reduction": pathway_a.get(
                "downstream_verifier_calls_reduction"
            ),
            "reuse_of_compressed_structure_count": pathway_a.get(
                "reuse_of_compressed_structure_count"
            ),
            "pathway_a_vs_cache_only_ablation": pathway_a.get("pathway_a_vs_cache_only_ablation"),
            "pathway_a_vs_no_pathway_a_ablation": pathway_a.get(
                "pathway_a_vs_no_pathway_a_ablation"
            ),
        },
        "proposal_precision_campaign": {
            "family": proposal_precision.get("family"),
            "recommended_policy": proposal_precision.get("selection", {}).get("recommended_policy"),
            "fixed_model_held_constant": proposal_precision.get("checks", {}).get(
                "fixed_model_held_constant"
            ),
            "fixed_pool_source": proposal_precision.get("fixed_proposal_pool", {}).get(
                "pool_source"
            ),
            "false_accept_rate": precision_quality.get("false_accept_rate"),
            "useful_recall": precision_quality.get("useful_recall"),
            "triage_precision": precision_quality.get("triage_precision"),
            "useful_accepted_before_first_symbol": precision_quality.get(
                "useful_accepted_before_first_symbol"
            ),
            "cycles_to_useful_outcome": precision_runtime.get("cycles_to_useful_outcome"),
            "verifier_calls_to_useful_outcome": precision_runtime.get(
                "verifier_calls_to_useful_outcome"
            ),
            "contradiction_before_acceptance": precision_runtime.get(
                "contradiction_before_acceptance"
            ),
            "zero_direct_ontology_mutation": precision_quality_summary.get(
                "ontology_mutated_directly"
            )
            is False,
        },
        "live_model_contribution": {
            "median_cycle_reduction": gauntlet.get("summary_metrics", {}).get(
                "live_proposal_cycle_reduction_median"
            ),
            "contradiction_reduction_before_acceptance": comparison,
            "protocol_false_accept_rate": proposal_quality.get("metrics", {}).get(
                "false_accept_rate"
            ),
            "precision_campaign_false_accept_rate": precision_quality.get("false_accept_rate"),
            "zero_direct_ontology_mutation": (
                proposal_quality.get("ontology_mutated_directly") is False
                and precision_quality_summary.get("ontology_mutated_directly") is False
            ),
        },
        "verifier_reliability": {
            "agreement_rate": verifier_agreement.get("agreement_rate"),
            "disagreement_rate": verifier_agreement.get("disagreement_rate"),
            "disagreement_resolved_rate": verifier_agreement.get("disagreement_resolved_rate"),
            "effective_agreement_quality": verifier_agreement.get("effective_agreement_quality"),
            "unresolved_disagreement_count": verifier_agreement.get(
                "unresolved_disagreement_count"
            ),
            "contradiction_added_from_disagreement_count": verifier_agreement.get(
                "contradiction_added_from_disagreement_count"
            ),
            "verifier_surface_pairs": verifier_agreement.get("verifier_surface_pairs"),
            "family_diagnostics": verifier_agreement.get("family_diagnostics"),
        },
        "provenance": {
            "git_sha": proof_manifest.get("git_sha"),
            "git_dirty": proof_manifest.get("git_dirty"),
            "git_dirty_source": proof_manifest.get(
                "git_dirty_source", proof_manifest.get("git_dirty")
            ),
            "git_dirty_full": proof_manifest.get("git_dirty_full", proof_manifest.get("git_dirty")),
            "git_dirty_source_excludes": proof_manifest.get("git_dirty_source_excludes", []),
            "artifact_versions": proof_manifest.get("artifact_versions"),
            "commands_used": proof_manifest.get("commands_used"),
            "model_backend_manifest": proof_manifest.get("model_backend_manifest"),
            "fixture_hash_count": len(proof_manifest.get("fixture_hashes", [])),
            "core_frozen": proof_manifest.get("core_frozen"),
        },
        "checks": checks,
    }


def markdown_from_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Final Proof Bundle",
        "",
        f"- pathway_b_non_regressed: `{summary['checks']['pathway_b_non_regressed']}`",
        f"- pathway_a_real: `{summary['checks']['pathway_a_real']}`",
        f"- verifier_reliability_operationalized: `{summary['checks']['verifier_reliability_operationalized']}`",
        f"- provenance_hardened: `{summary['checks']['provenance_hardened']}`",
        f"- proposal_quarantine_intact: `{summary['checks']['proposal_quarantine_intact']}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    version = artifact_version_info("phase11", root=ROOT)
    raw = {name: load_json(path) for name, path in RAW_SOURCES.items()}
    summary = build_summary(raw, version)
    write_json_artifact(
        ROOT / "artifacts" / "phase11" / "final_proof_bundle.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase11_final_proof_report.md",
        markdown_from_summary(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
