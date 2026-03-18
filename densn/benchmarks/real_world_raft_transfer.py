"""Cross-repo transfer between real-world Raft artifact bundles."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..artifacts import load_manifest
from ..memory import OntologyRegistry
from ..system import DENSNSystem
from .gauntlet_support import (
    build_commit_family_graph_from_manifest,
    claim_for_meta_symbol,
    integrate_secondary_verifier_evidence,
    register_secondary_verifiers,
    reuse_only_config,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_DIR = ROOT / "artifacts" / "real_world"
ETCD_SUMMARY_PATH = REAL_WORLD_DIR / "etcd_raft_current_term_summary.json"
ETCD_REGISTRY_PATH = REAL_WORLD_DIR / "etcd_raft_current_term_registry.json"
RAFT_RS_SUMMARY_PATH = REAL_WORLD_DIR / "raft_rs_read_index_current_term_summary.json"
RAFT_RS_REGISTRY_PATH = REAL_WORLD_DIR / "raft_rs_read_index_current_term_registry.json"
ETCD_MANIFEST_PATH = ROOT / "fixtures" / "etcd_raft_current_term" / "train" / "manifest.json"
RAFT_RS_MANIFEST_PATH = (
    ROOT / "fixtures" / "raft_rs_read_index_current_term" / "train" / "manifest.json"
)
ETCD_VERIFIER_SCRIPT = ROOT / "verifiers" / "etcd_raft_current_term_verifier.py"
RAFT_RS_VERIFIER_SCRIPT = ROOT / "verifiers" / "raft_rs_read_index_current_term_verifier.py"
ETCD_CLAIM_KIND = "etcd_raft_current_term_invariant"
RAFT_RS_CLAIM_KIND = "raft_rs_read_index_current_term_invariant"


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _accepted_record(registry: OntologyRegistry) -> tuple[str, dict[str, Any]]:
    for meta_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_id, record
    raise RuntimeError(f"No accepted record found in registry {registry!r}.")


def _run_transfer_case(
    *,
    source_family: str,
    target_label: str,
    source_registry_path: Path,
    source_summary_path: Path,
    target_manifest_path: Path,
    target_claim_kind: str,
    target_verifier_script: Path,
) -> dict[str, Any]:
    source_registry = OntologyRegistry.load(str(source_registry_path))
    source_summary = _load_json(source_summary_path)
    source_meta_id, source_record = _accepted_record(source_registry)
    target_manifest = load_manifest(target_manifest_path)

    baseline_system = DENSNSystem(
        build_commit_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_label.upper()}_BASELINE"
        ),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        build_commit_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_label.upper()}_REUSE"
        ),
        reuse_only_config(),
        registry=source_registry,
    )
    register_secondary_verifiers(
        reuse_system,
        claim_kind=target_claim_kind,
        subprocess_command=[sys.executable, str(target_verifier_script)],
        cwd=str(ROOT),
    )
    reuse_applications = reuse_system.apply_reusable_symbols(
        task_id=target_manifest["task_id"], graph=reuse_system.graph
    )
    reuse_summary = reuse_system.run_until_stable()

    verifier_results: list[dict[str, Any]] = []
    verifier_agreement = None
    mapping_class = None
    mapping_confidence = None
    instantiated_meta_symbol_id = None
    if reuse_applications:
        application = reuse_applications[0]
        mapping_class = application.get("mapping_class")
        mapping_confidence = application.get("mapping_confidence")
        instantiated_meta_symbol_id = application.get("instantiated_meta_symbol_id")
        claim = claim_for_meta_symbol(
            reuse_system,
            meta_symbol_id=str(instantiated_meta_symbol_id),
            manifest_path=target_manifest_path,
            claim_kind=target_claim_kind,
            record=source_record,
        )
        results = reuse_system.verifier.verify_all(claim)
        integrate_secondary_verifier_evidence(
            reuse_system,
            node_id=str(instantiated_meta_symbol_id),
            results=results,
        )
        verifier_results = [result.__dict__ for result in results]
        verifier_agreement = reuse_system.verifier.agreement_summary(results)

    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        reuse_summary.get("final_psi") or 0.0
    )
    return {
        "source_family": source_family,
        "source_meta_symbol_id": source_meta_id,
        "target_family": target_manifest.get("family"),
        "target_task_id": target_manifest.get("task_id"),
        "mapping_class": mapping_class,
        "mapping_confidence": mapping_confidence,
        "baseline_final_psi": float(baseline_summary.get("final_psi") or 0.0),
        "transfer_final_psi": float(reuse_summary.get("final_psi") or 0.0),
        "contradiction_gain": contradiction_gain,
        "reuse_application_count": len(reuse_applications),
        "instantiated_meta_symbol_id": instantiated_meta_symbol_id,
        "verifier_results": verifier_results,
        "verifier_agreement": verifier_agreement,
        "source_runtime_metrics": source_summary.get("train_summary", {}).get(
            "runtime_metrics", {}
        ),
        "target_baseline_runtime_metrics": baseline_summary.get("runtime_metrics", {}),
        "target_transfer_runtime_metrics": reuse_summary.get("runtime_metrics", {}),
        "positive_transfer": bool(
            reuse_applications
            and contradiction_gain > 0.0
            and verifier_agreement
            and verifier_agreement.get("all_agree")
            and all(result.get("passed") for result in verifier_results)
        ),
    }


def run_real_world_raft_transfer(output_dir: str = "artifacts/real_world") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    rows = [
        _run_transfer_case(
            source_family="etcd_raft_current_term",
            target_label="raft_rs_read_index_current_term",
            source_registry_path=ETCD_REGISTRY_PATH,
            source_summary_path=ETCD_SUMMARY_PATH,
            target_manifest_path=RAFT_RS_MANIFEST_PATH,
            target_claim_kind=RAFT_RS_CLAIM_KIND,
            target_verifier_script=RAFT_RS_VERIFIER_SCRIPT,
        ),
        _run_transfer_case(
            source_family="raft_rs_read_index_current_term",
            target_label="etcd_raft_current_term",
            source_registry_path=RAFT_RS_REGISTRY_PATH,
            source_summary_path=RAFT_RS_SUMMARY_PATH,
            target_manifest_path=ETCD_MANIFEST_PATH,
            target_claim_kind=ETCD_CLAIM_KIND,
            target_verifier_script=ETCD_VERIFIER_SCRIPT,
        ),
    ]

    summary = {
        "artifact_version": version,
        "domain": "real_world_raft_transfer",
        "rows": rows,
        "checks": {
            "all_positive_transfers": all(row.get("positive_transfer") for row in rows),
            "all_role_remap": all(row.get("mapping_class") == "role_remap" for row in rows),
            "all_zero_final_tension": all(
                float(row.get("transfer_final_psi") or 0.0) <= 0.0 for row in rows
            ),
        },
    }
    write_json_artifact(
        target_dir / "real_world_raft_transfer_summary.json", summary, version=version
    )
    return summary
