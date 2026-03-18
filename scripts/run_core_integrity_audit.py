"""Audit whether the current implementation is core-first rather than benchmark-first."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact

CORE_DIR = ROOT / "densn"
BENCHMARK_DIR = CORE_DIR / "benchmarks"
ARTIFACT_DIR = ROOT / "artifacts"
OUTPUT_DIR = ARTIFACT_DIR / "readiness"


BENCHMARK_TOKENS = {
    "window_verifier",
    "heldout_window",
    "CosmicBanana",
    "SessionWindow",
    "payload_requires_open",
    "formal_window",
    "proposal_quality",
}


def python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py"))


def scan_core_for_benchmark_imports() -> list[dict]:
    findings: list[dict] = []
    for path in python_files(CORE_DIR):
        if BENCHMARK_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "benchmarks" in node.module:
                    findings.append({"path": str(path.relative_to(ROOT)), "module": node.module})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "benchmarks" in alias.name:
                        findings.append({"path": str(path.relative_to(ROOT)), "module": alias.name})
    return findings


def scan_core_for_benchmark_tokens() -> list[dict]:
    findings: list[dict] = []
    for path in python_files(CORE_DIR):
        if BENCHMARK_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for token in sorted(BENCHMARK_TOKENS):
            if token in text:
                findings.append({"path": str(path.relative_to(ROOT)), "token": token})
    return findings


def scan_benchmarks_for_private_core_calls() -> list[dict]:
    findings: list[dict] = []
    for path in python_files(BENCHMARK_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and not node.attr.startswith("__")
            ):
                findings.append({"path": str(path.relative_to(ROOT)), "attribute": node.attr})
    return findings


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def find_graph_meta_symbol(graph_snapshot: dict, meta_symbol_id: str) -> dict:
    for node in graph_snapshot.get("nodes", []):
        if node.get("id") == meta_symbol_id:
            return node
    return {}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("readiness", root=ROOT)

    core_import_findings = scan_core_for_benchmark_imports()
    token_findings = scan_core_for_benchmark_tokens()
    private_call_findings = scan_benchmarks_for_private_core_calls()

    proposal_audit = load_json(ARTIFACT_DIR / "phase2" / "proposal_audit_summary.json")
    formal_summary = load_json(ARTIFACT_DIR / "phase1" / "formal_summary.json")
    xor_summary = load_json(ARTIFACT_DIR / "phase0" / "xor_summary.json")
    formal_registry = load_json(ARTIFACT_DIR / "phase1" / "formal_registry.json")
    formal_graph = load_json(ARTIFACT_DIR / "phase1" / "formal_train_graph.json")
    formal_telemetry = load_json(ARTIFACT_DIR / "phase1" / "formal_train_telemetry_summary.json")
    if not formal_telemetry:
        formal_telemetry = formal_summary.get("train_summary", {}).get("telemetry_summary", {})

    accepted_meta_symbol_id = str(formal_summary.get("accepted_meta_symbol_id") or "")
    registry_record = dict(formal_registry.get(accepted_meta_symbol_id, {}))
    graph_record = find_graph_meta_symbol(formal_graph, accepted_meta_symbol_id)
    lifecycle_consistent = (
        bool(accepted_meta_symbol_id)
        and registry_record
        and graph_record
        and (
            registry_record.get("status") == graph_record.get("admission_status")
            and registry_record.get("semantic_label") == graph_record.get("semantic_label")
            and registry_record.get("semantic_status") == graph_record.get("semantic_status")
        )
    )

    readiness = {
        "core_imports_benchmark_free": len(core_import_findings) == 0,
        "core_tokens_benchmark_free": len(token_findings) == 0,
        "benchmarks_use_public_core_api_only": len(private_call_findings) == 0,
        "proposal_quarantine_non_mutating": proposal_audit.get("ontology_mutated_directly")
        is False,
        "xor_zero_tension": xor_summary.get("final_psi") == 0.0,
        "formal_has_accepted_symbol": bool(formal_summary.get("accepted_meta_symbol_id")),
        "formal_reports_multiple_heldout_cases": int(
            formal_summary.get("accountability", {}).get("heldout_case_count", 0)
        )
        >= 2,
        "formal_candidate_lifecycle_logged": int(
            formal_telemetry.get("event_type_counts", {}).get("candidate_evaluated", 0)
        )
        >= 1,
        "formal_registry_graph_lifecycle_consistent": lifecycle_consistent,
    }
    readiness["proceed_recommended"] = all(readiness.values())

    summary = {
        "artifact_version": version,
        "core_import_findings": core_import_findings,
        "benchmark_token_findings": token_findings,
        "private_core_call_findings": private_call_findings,
        "proposal_audit": {
            "ontology_mutated_directly": proposal_audit.get("ontology_mutated_directly"),
            "proposal_status_counts": proposal_audit.get("proposal_summary", {}).get(
                "status_counts", {}
            ),
        },
        "xor_summary": {
            "final_psi": xor_summary.get("final_psi"),
            "registry": xor_summary.get("registry"),
        },
        "formal_summary": {
            "accepted_meta_symbol_id": accepted_meta_symbol_id,
            "heldout_case_count": formal_summary.get("accountability", {}).get(
                "heldout_case_count"
            ),
            "accepted_candidate_count": formal_summary.get("accountability", {}).get(
                "accepted_candidate_count"
            ),
            "rejected_candidate_count": formal_summary.get("accountability", {}).get(
                "rejected_candidate_count"
            ),
            "rollback_count": formal_summary.get("accountability", {}).get("rollback_count"),
            "heldout_results_count": len(
                formal_summary.get("accepted_admission_metrics", {}).get("heldout_results", [])
            ),
            "registry_status": registry_record.get("status"),
            "graph_admission_status": graph_record.get("admission_status"),
            "registry_semantic_label": registry_record.get("semantic_label"),
            "graph_semantic_label": graph_record.get("semantic_label"),
        },
        "readiness": readiness,
    }

    write_json_artifact(OUTPUT_DIR / "core_integrity_audit.json", summary, version=version)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
