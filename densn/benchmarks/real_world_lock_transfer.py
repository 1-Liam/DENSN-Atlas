"""Cross-repo transfer between real-world lock/refresh artifact bundles."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..system import DENSNSystem
from .gauntlet_support import (
    build_window_family_graph_from_manifest,
    claim_for_meta_symbol,
    claim_without_application,
    integrate_secondary_verifier_evidence,
    register_secondary_verifiers,
    reuse_only_config,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_DIR = ROOT / "artifacts" / "real_world"
REDSYNC_SUMMARY_PATH = REAL_WORLD_DIR / "redsync_mutex_extend_summary.json"
REDSYNC_REGISTRY_PATH = REAL_WORLD_DIR / "redsync_mutex_extend_registry.json"
REDISLOCK_SUMMARY_PATH = REAL_WORLD_DIR / "redislock_refresh_summary.json"
REDISLOCK_REGISTRY_PATH = REAL_WORLD_DIR / "redislock_refresh_registry.json"
CREDIT_SUMMARY_PATH = ROOT / "artifacts" / "phase12" / "credit_window_summary.json"
CREDIT_REGISTRY_PATH = ROOT / "artifacts" / "phase12" / "credit_window_registry.json"
REDSYNC_MANIFEST_PATH = ROOT / "fixtures" / "redsync_mutex_extend" / "train" / "manifest.json"
REDISLOCK_MANIFEST_PATH = ROOT / "fixtures" / "redislock_refresh" / "train" / "manifest.json"
CREDIT_MANIFEST_PATH = ROOT / "fixtures" / "credit_window" / "train" / "manifest.json"
REDSYNC_VERIFIER_SCRIPT = ROOT / "verifiers" / "redsync_mutex_extend_verifier.py"
REDISLOCK_VERIFIER_SCRIPT = ROOT / "verifiers" / "redislock_refresh_verifier.py"
CREDIT_VERIFIER_SCRIPT = ROOT / "verifiers" / "credit_window_verifier.py"
REDSYNC_CLAIM_KIND = "redsync_mutex_extend_invariant"
REDISLOCK_CLAIM_KIND = "redislock_refresh_invariant"
CREDIT_CLAIM_KIND = "credit_window_invariant"


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
    source_registry_path: Path,
    source_summary_path: Path,
    target_manifest_path: Path,
    target_claim_kind: str,
    target_verifier_script: Path,
) -> dict[str, Any]:
    source_registry = OntologyRegistry.load(str(source_registry_path))
    source_summary = _load_json(source_summary_path)
    source_meta_id, source_record = _accepted_record(source_registry)
    target_manifest = _load_json(target_manifest_path)

    baseline_system = DENSNSystem(
        build_window_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_manifest['task_id'].upper()}_BASELINE"
        ),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        build_window_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_manifest['task_id'].upper()}_REUSE"
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
        "case_kind": "positive_transfer",
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
        "positive_transfer": bool(
            reuse_applications
            and contradiction_gain > 0.0
            and verifier_agreement
            and verifier_agreement.get("all_agree")
            and all(result.get("passed") for result in verifier_results)
        ),
    }


def _run_negative_case(
    *,
    source_family: str,
    source_registry_path: Path,
    source_summary_path: Path,
    target_manifest_path: Path,
    target_claim_kind: str,
    target_verifier_script: Path,
) -> dict[str, Any]:
    source_registry = OntologyRegistry.load(str(source_registry_path))
    source_summary = _load_json(source_summary_path)
    _, source_record = _accepted_record(source_registry)
    target_manifest = _load_json(target_manifest_path)

    baseline_system = DENSNSystem(
        build_window_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_manifest['task_id'].upper()}_NEG_BASELINE"
        ),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        build_window_family_graph_from_manifest(
            target_manifest_path, prefix=f"{target_manifest['task_id'].upper()}_NEG_REUSE"
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

    if reuse_applications:
        application = reuse_applications[0]
        mapping_class = application.get("mapping_class")
        results = reuse_system.verifier.verify_all(
            claim_for_meta_symbol(
                reuse_system,
                meta_symbol_id=str(application["instantiated_meta_symbol_id"]),
                manifest_path=target_manifest_path,
                claim_kind=target_claim_kind,
                record=source_record,
            )
        )
    else:
        mapping_class = "invalid_transfer"
        results = reuse_system.verifier.verify_all(
            claim_without_application(
                manifest_path=target_manifest_path,
                claim_kind=target_claim_kind,
                record=source_record,
            )
        )
    verifier_results = [result.__dict__ for result in results]
    verifier_agreement = reuse_system.verifier.agreement_summary(results)
    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        reuse_summary.get("final_psi") or 0.0
    )
    return {
        "source_family": source_family,
        "target_family": target_manifest.get("family"),
        "target_task_id": target_manifest.get("task_id"),
        "case_kind": "negative_transfer",
        "mapping_class": mapping_class,
        "baseline_final_psi": float(baseline_summary.get("final_psi") or 0.0),
        "transfer_final_psi": float(reuse_summary.get("final_psi") or 0.0),
        "contradiction_gain": contradiction_gain,
        "reuse_application_count": len(reuse_applications),
        "verifier_results": verifier_results,
        "verifier_agreement": verifier_agreement,
        "source_runtime_metrics": source_summary.get("train_summary", {}).get(
            "runtime_metrics", {}
        ),
        "positive_transfer": False,
    }


def run_real_world_lock_transfer(output_dir: str = "artifacts/real_world") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    rows = [
        _run_transfer_case(
            source_family="redsync_mutex_extend",
            source_registry_path=REDSYNC_REGISTRY_PATH,
            source_summary_path=REDSYNC_SUMMARY_PATH,
            target_manifest_path=REDISLOCK_MANIFEST_PATH,
            target_claim_kind=REDISLOCK_CLAIM_KIND,
            target_verifier_script=REDISLOCK_VERIFIER_SCRIPT,
        ),
        _run_transfer_case(
            source_family="redislock_refresh",
            source_registry_path=REDISLOCK_REGISTRY_PATH,
            source_summary_path=REDISLOCK_SUMMARY_PATH,
            target_manifest_path=REDSYNC_MANIFEST_PATH,
            target_claim_kind=REDSYNC_CLAIM_KIND,
            target_verifier_script=REDSYNC_VERIFIER_SCRIPT,
        ),
        _run_negative_case(
            source_family="credit_window",
            source_registry_path=CREDIT_REGISTRY_PATH,
            source_summary_path=CREDIT_SUMMARY_PATH,
            target_manifest_path=REDISLOCK_MANIFEST_PATH,
            target_claim_kind=REDISLOCK_CLAIM_KIND,
            target_verifier_script=REDISLOCK_VERIFIER_SCRIPT,
        ),
        _run_negative_case(
            source_family="redislock_refresh",
            source_registry_path=REDISLOCK_REGISTRY_PATH,
            source_summary_path=REDISLOCK_SUMMARY_PATH,
            target_manifest_path=CREDIT_MANIFEST_PATH,
            target_claim_kind=CREDIT_CLAIM_KIND,
            target_verifier_script=CREDIT_VERIFIER_SCRIPT,
        ),
    ]

    positive_rows = [row for row in rows if row.get("case_kind") == "positive_transfer"]
    negative_rows = [row for row in rows if row.get("case_kind") == "negative_transfer"]

    summary = {
        "artifact_version": version,
        "domain": "real_world_lock_transfer",
        "rows": rows,
        "transfer_metrics": transfer_metrics_summary(
            transfer_results=[
                {
                    "verification": {
                        "passed": bool(row.get("verifier_results"))
                        and all(result.get("passed") for result in row.get("verifier_results", [])),
                    },
                    "summary": {
                        "final_psi": row.get("transfer_final_psi"),
                    },
                    "contradiction_gain": row.get("contradiction_gain"),
                }
                for row in positive_rows
            ]
        ),
        "checks": {
            "positive_cases_pass": all(row.get("positive_transfer") for row in positive_rows),
            "positive_cases_are_role_remap": all(
                row.get("mapping_class") == "role_remap" for row in positive_rows
            ),
            "positive_cases_zero_final_tension": all(
                float(row.get("transfer_final_psi") or 0.0) <= 0.0 for row in positive_rows
            ),
            "negative_cases_blocked": all(
                not row.get("positive_transfer") for row in negative_rows
            ),
            "negative_cases_explained_by_no_application_or_verifier_failure": all(
                row.get("reuse_application_count", 0) == 0
                or any(not result.get("passed") for result in row.get("verifier_results", []))
                for row in negative_rows
            ),
        },
    }
    write_json_artifact(
        target_dir / "real_world_lock_transfer_summary.json", summary, version=version
    )
    return summary
