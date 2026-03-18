"""Unified real-world gauntlet across external commit and lock families."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from ..artifact_store import artifact_version_info, write_json_artifact
from ..memory import OntologyRegistry
from ..system import DENSNSystem
from .gauntlet_support import (
    build_commit_family_graph_from_manifest,
    build_window_family_graph_from_manifest,
    claim_for_meta_symbol,
    claim_without_application,
    register_secondary_verifiers,
    reuse_only_config,
)
from .real_world_lock_transfer import run_real_world_lock_transfer
from .real_world_raft_transfer import run_real_world_raft_transfer

ROOT = Path(__file__).resolve().parents[2]
REAL_WORLD_DIR = ROOT / "artifacts" / "real_world"
ETCD_SUMMARY_PATH = REAL_WORLD_DIR / "etcd_raft_current_term_summary.json"
RAFT_RS_SUMMARY_PATH = REAL_WORLD_DIR / "raft_rs_read_index_current_term_summary.json"
REDSYNC_SUMMARY_PATH = REAL_WORLD_DIR / "redsync_mutex_extend_summary.json"
REDISLOCK_SUMMARY_PATH = REAL_WORLD_DIR / "redislock_refresh_summary.json"
ETCD_REGISTRY_PATH = REAL_WORLD_DIR / "etcd_raft_current_term_registry.json"
RAFT_RS_REGISTRY_PATH = REAL_WORLD_DIR / "raft_rs_read_index_current_term_registry.json"
REDSYNC_REGISTRY_PATH = REAL_WORLD_DIR / "redsync_mutex_extend_registry.json"
REDISLOCK_REGISTRY_PATH = REAL_WORLD_DIR / "redislock_refresh_registry.json"
ETCD_MANIFEST_PATH = ROOT / "fixtures" / "etcd_raft_current_term" / "train" / "manifest.json"
RAFT_RS_MANIFEST_PATH = (
    ROOT / "fixtures" / "raft_rs_read_index_current_term" / "train" / "manifest.json"
)
REDSYNC_MANIFEST_PATH = ROOT / "fixtures" / "redsync_mutex_extend" / "train" / "manifest.json"
REDISLOCK_MANIFEST_PATH = ROOT / "fixtures" / "redislock_refresh" / "train" / "manifest.json"
ETCD_VERIFIER_SCRIPT = ROOT / "verifiers" / "etcd_raft_current_term_verifier.py"
RAFT_RS_VERIFIER_SCRIPT = ROOT / "verifiers" / "raft_rs_read_index_current_term_verifier.py"
REDSYNC_VERIFIER_SCRIPT = ROOT / "verifiers" / "redsync_mutex_extend_verifier.py"
REDISLOCK_VERIFIER_SCRIPT = ROOT / "verifiers" / "redislock_refresh_verifier.py"
ETCD_CLAIM_KIND = "etcd_raft_current_term_invariant"
RAFT_RS_CLAIM_KIND = "raft_rs_read_index_current_term_invariant"
REDSYNC_CLAIM_KIND = "redsync_mutex_extend_invariant"
REDISLOCK_CLAIM_KIND = "redislock_refresh_invariant"


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _accepted_record(registry: OntologyRegistry) -> tuple[str, dict[str, Any]]:
    for meta_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_id, record
    raise RuntimeError(f"No accepted record found in registry {registry!r}.")


def _compact_source_summary(name: str, summary: dict[str, Any]) -> dict[str, Any]:
    train_summary = dict(summary.get("train_summary", {}))
    verifier_agreement = dict(summary.get("verifier_agreement") or {})
    return {
        "family": name,
        "domain": summary.get("domain"),
        "artifact_version": summary.get("artifact_version"),
        "source_provenance": summary.get("source_provenance", {}),
        "final_psi": train_summary.get("final_psi"),
        "cycles_run": train_summary.get("cycles_run"),
        "accepted_meta_symbol_id": summary.get("accepted_meta_symbol_id"),
        "accepted_interface_is_constant": summary.get("accepted_interface_is_constant"),
        "verifier_agreement": verifier_agreement,
        "baseline_no_tsl": (summary.get("baseline_no_tsl") or {}).get("final_psi"),
        "baseline_no_conflict_memory": (summary.get("baseline_no_conflict_memory") or {}).get(
            "final_psi"
        ),
        "checks": summary.get("checks", {}),
    }


def _run_cross_mechanism_negative_case(
    *,
    case_id: str,
    source_family: str,
    source_registry_path: Path,
    source_summary_path: Path,
    target_family: str,
    target_manifest_path: Path,
    target_claim_kind: str,
    target_verifier_script: Path,
    graph_builder: Callable[..., Any],
) -> dict[str, Any]:
    source_registry = OntologyRegistry.load(str(source_registry_path))
    source_summary = _load_json(source_summary_path)
    _, source_record = _accepted_record(source_registry)
    target_manifest = _load_json(target_manifest_path)

    baseline_system = DENSNSystem(
        graph_builder(target_manifest_path, prefix=f"{case_id.upper()}_BASELINE"),
        reuse_only_config(),
        registry=OntologyRegistry(),
    )
    baseline_summary = baseline_system.run_until_stable()

    reuse_system = DENSNSystem(
        graph_builder(target_manifest_path, prefix=f"{case_id.upper()}_REUSE"),
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
        claim = claim_for_meta_symbol(
            reuse_system,
            meta_symbol_id=str(application["instantiated_meta_symbol_id"]),
            manifest_path=target_manifest_path,
            claim_kind=target_claim_kind,
            record=source_record,
        )
    else:
        mapping_class = "invalid_transfer"
        claim = claim_without_application(
            manifest_path=target_manifest_path,
            claim_kind=target_claim_kind,
            record=source_record,
        )
    results = reuse_system.verifier.verify_all(claim)
    verifier_results = [result.__dict__ for result in results]
    verifier_agreement = reuse_system.verifier.agreement_summary(results)
    contradiction_gain = float(baseline_summary.get("final_psi") or 0.0) - float(
        reuse_summary.get("final_psi") or 0.0
    )
    return {
        "case_id": case_id,
        "source_family": source_family,
        "target_family": target_family,
        "case_kind": "cross_mechanism_negative_transfer",
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
        "blocked": (
            len(reuse_applications) == 0
            or any(not result.get("passed") for result in verifier_results)
        ),
    }


def run_real_world_gauntlet(output_dir: str = "artifacts/real_world") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    source_summaries = {
        "etcd_raft_current_term": _load_json(ETCD_SUMMARY_PATH),
        "raft_rs_read_index_current_term": _load_json(RAFT_RS_SUMMARY_PATH),
        "redsync_mutex_extend": _load_json(REDSYNC_SUMMARY_PATH),
        "redislock_refresh": _load_json(REDISLOCK_SUMMARY_PATH),
    }

    raft_transfer = run_real_world_raft_transfer(output_dir=output_dir)
    lock_transfer = run_real_world_lock_transfer(output_dir=output_dir)

    cross_mechanism_rows = [
        _run_cross_mechanism_negative_case(
            case_id="redsync_to_etcd",
            source_family="redsync_mutex_extend",
            source_registry_path=REDSYNC_REGISTRY_PATH,
            source_summary_path=REDSYNC_SUMMARY_PATH,
            target_family="etcd_raft_current_term",
            target_manifest_path=ETCD_MANIFEST_PATH,
            target_claim_kind=ETCD_CLAIM_KIND,
            target_verifier_script=ETCD_VERIFIER_SCRIPT,
            graph_builder=build_commit_family_graph_from_manifest,
        ),
        _run_cross_mechanism_negative_case(
            case_id="etcd_to_redsync",
            source_family="etcd_raft_current_term",
            source_registry_path=ETCD_REGISTRY_PATH,
            source_summary_path=ETCD_SUMMARY_PATH,
            target_family="redsync_mutex_extend",
            target_manifest_path=REDSYNC_MANIFEST_PATH,
            target_claim_kind=REDSYNC_CLAIM_KIND,
            target_verifier_script=REDSYNC_VERIFIER_SCRIPT,
            graph_builder=build_window_family_graph_from_manifest,
        ),
        _run_cross_mechanism_negative_case(
            case_id="redislock_to_raft_rs",
            source_family="redislock_refresh",
            source_registry_path=REDISLOCK_REGISTRY_PATH,
            source_summary_path=REDISLOCK_SUMMARY_PATH,
            target_family="raft_rs_read_index_current_term",
            target_manifest_path=RAFT_RS_MANIFEST_PATH,
            target_claim_kind=RAFT_RS_CLAIM_KIND,
            target_verifier_script=RAFT_RS_VERIFIER_SCRIPT,
            graph_builder=build_commit_family_graph_from_manifest,
        ),
        _run_cross_mechanism_negative_case(
            case_id="raft_rs_to_redislock",
            source_family="raft_rs_read_index_current_term",
            source_registry_path=RAFT_RS_REGISTRY_PATH,
            source_summary_path=RAFT_RS_SUMMARY_PATH,
            target_family="redislock_refresh",
            target_manifest_path=REDISLOCK_MANIFEST_PATH,
            target_claim_kind=REDISLOCK_CLAIM_KIND,
            target_verifier_script=REDISLOCK_VERIFIER_SCRIPT,
            graph_builder=build_window_family_graph_from_manifest,
        ),
    ]

    positive_rows = [
        *list(raft_transfer.get("rows", [])),
        *[
            row
            for row in lock_transfer.get("rows", [])
            if row.get("case_kind") == "positive_transfer"
        ],
    ]

    summary = {
        "artifact_version": version,
        "domain": "real_world_gauntlet",
        "source_families": [
            _compact_source_summary(name, summary) for name, summary in source_summaries.items()
        ],
        "positive_transfer_rows": positive_rows,
        "cross_mechanism_negative_rows": cross_mechanism_rows,
        "supporting_artifacts": {
            "real_world_raft_transfer": str(
                (target_dir / "real_world_raft_transfer_summary.json").resolve()
            ),
            "real_world_lock_transfer": str(
                (target_dir / "real_world_lock_transfer_summary.json").resolve()
            ),
        },
        "checks": {
            "external_family_count_is_four": len(source_summaries) == 4,
            "all_external_source_solves_pass": all(
                bool(item.get("checks", {}).get("accepted_symbol"))
                and bool(item.get("checks", {}).get("final_psi_zero"))
                and bool(item.get("checks", {}).get("verifier_surfaces_agree"))
                for item in [
                    _compact_source_summary(name, summary)
                    for name, summary in source_summaries.items()
                ]
            ),
            "within_mechanism_positive_transfers_pass": all(
                bool(row.get("positive_transfer")) and row.get("mapping_class") == "role_remap"
                for row in positive_rows
            ),
            "within_mechanism_transfer_count_is_four": len(positive_rows) == 4,
            "cross_mechanism_negative_cases_blocked": all(
                row.get("blocked") for row in cross_mechanism_rows
            ),
            "cross_mechanism_negative_case_count_is_four": len(cross_mechanism_rows) == 4,
            "cross_mechanism_failures_are_explicit": all(
                any(not result.get("passed") for result in row.get("verifier_results", []))
                for row in cross_mechanism_rows
            ),
        },
        "metrics": {
            "positive_transfer_count": sum(
                1 for row in positive_rows if row.get("positive_transfer")
            ),
            "cross_mechanism_block_count": sum(
                1 for row in cross_mechanism_rows if row.get("blocked")
            ),
            "positive_transfer_contradiction_gain_sum": sum(
                float(row.get("contradiction_gain") or 0.0) for row in positive_rows
            ),
            "cross_mechanism_negative_contradiction_gain_sum": sum(
                float(row.get("contradiction_gain") or 0.0) for row in cross_mechanism_rows
            ),
        },
    }
    write_json_artifact(target_dir / "real_world_gauntlet_summary.json", summary, version=version)
    return summary
