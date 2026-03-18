"""Real-world external evaluation on bsm/redislock refresh safety."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..artifacts import load_manifest
from ..memory import OntologyRegistry
from ..proof_contract import CORE_API_VERSION
from ..system import DENSNConfig, DENSNSystem
from .gauntlet_support import (
    build_window_family_graph_from_manifest,
    claim_for_meta_symbol,
    integrate_secondary_verifier_evidence,
    register_secondary_verifiers,
    runtime_row_fields,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "fixtures" / "redislock_refresh"
MANIFEST_PATH = FIXTURES_DIR / "train" / "manifest.json"
VERIFIER_SCRIPT = ROOT / "verifiers" / "redislock_refresh_verifier.py"
CLAIM_KIND = "redislock_refresh_invariant"


def real_world_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=5.0,
        pathway_b_persistence_threshold=6.0,
        plateau_window=3,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=16,
        random_seed=7,
        require_verifier_for_admission=True,
        require_reuse_for_admission=False,
        min_heldout_contradiction_gain=0.0,
        max_complexity_penalty=10.0,
        candidate_labels=["RefreshWindowReady", "RedislockRefreshWindow"],
    )


def no_tsl_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=999.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=8,
        random_seed=7,
    )


def no_conflict_memory_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.0,
        max_weight_multiplier=1.0,
        frustration_threshold=5.0,
        pathway_b_persistence_threshold=999.0,
        plateau_window=999,
        plateau_epsilon=1e-9,
        phi_threshold=10.0,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=8,
        random_seed=7,
    )


def _accepted_meta_record(registry: OntologyRegistry) -> tuple[str | None, dict[str, Any] | None]:
    for meta_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_id, record
    return None, None


def _interface_is_constant(record: dict[str, Any] | None) -> bool | None:
    if record is None:
        return None
    truth_table = record.get("interface_definition", {}).get("truth_table", {})
    if not truth_table:
        return None
    return len({bool(value) for value in truth_table.values()}) == 1


def _register_verifiers(system: DENSNSystem) -> None:
    register_secondary_verifiers(
        system,
        claim_kind=CLAIM_KIND,
        subprocess_command=[sys.executable, str(VERIFIER_SCRIPT)],
        cwd=str(ROOT),
    )


def _make_graph(prefix: str) -> Any:
    return build_window_family_graph_from_manifest(MANIFEST_PATH, prefix=prefix)


def _candidate_evaluator(system: DENSNSystem, context: dict[str, Any]) -> dict[str, Any]:
    proposal = context["proposal"]
    record = system.registry.records.get(proposal.meta_symbol.id, {})
    claim = claim_for_meta_symbol(
        system,
        meta_symbol_id=proposal.meta_symbol.id,
        manifest_path=MANIFEST_PATH,
        claim_kind=CLAIM_KIND,
        record=record,
    )
    results = system.verifier.verify_all(claim)
    integrate_secondary_verifier_evidence(system, node_id=proposal.meta_symbol.id, results=results)
    agreement = system.verifier.agreement_summary(results)
    verifier_passed = bool(results) and all(result.passed for result in results)
    contradiction_gain = max(0.0, float(context["psi_before"]) - float(context["psi_after"]))
    return {
        "verifier_passed": verifier_passed,
        "verification_results": results,
        "verifier_agreement": agreement,
        "heldout_contradiction_gain": contradiction_gain,
        "rent_paid": contradiction_gain > 0.0 and verifier_passed,
    }


def run_real_world_redislock_benchmark(output_dir: str = "artifacts/real_world") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("real_world", root=ROOT)

    manifest = load_manifest(MANIFEST_PATH)
    registry = OntologyRegistry()
    train_system = DENSNSystem(
        _make_graph("REDISLOCK_REAL"), real_world_config(), registry=registry
    )
    _register_verifiers(train_system)
    train_system.register_candidate_evaluator(_candidate_evaluator)
    train_summary = train_system.run_until_stable()

    meta_id, record = _accepted_meta_record(registry)
    verification_results = [] if record is None else list(record.get("verifications", []))
    verifier_agreement = (
        None if record is None else record.get("admission_metrics", {}).get("verifier_agreement")
    )

    baseline_no_tsl_system = DENSNSystem(
        _make_graph("REDISLOCK_BASELINE_NO_TSL"), no_tsl_config(), registry=OntologyRegistry()
    )
    baseline_no_tsl_summary = baseline_no_tsl_system.run_until_stable()
    baseline_no_conflict_system = DENSNSystem(
        _make_graph("REDISLOCK_BASELINE_NO_CONFLICT"),
        no_conflict_memory_config(),
        registry=OntologyRegistry(),
    )
    baseline_no_conflict_summary = baseline_no_conflict_system.run_until_stable()

    graph_path = target_dir / "redislock_refresh_graph.json"
    train_system.graph.save(str(graph_path))
    telemetry_path = target_dir / "redislock_refresh_telemetry.jsonl"
    train_system.telemetry.flush(str(telemetry_path))
    registry_path = target_dir / "redislock_refresh_registry.json"
    registry.save(str(registry_path))

    baseline_gap = float(baseline_no_tsl_summary.get("final_psi") or 0.0) - float(
        train_summary.get("final_psi") or 0.0
    )
    proof_contract = {
        **train_system.core_contract(),
        "core_mode": "core_frozen",
        "core_api_version": CORE_API_VERSION,
        "runtime_metrics": train_summary.get("runtime_metrics", {}),
        "lifecycle_metrics": registry.lifecycle_summary(),
    }

    summary = {
        "artifact_version": version,
        "domain": "redislock_refresh_real_world",
        "source_manifest_path": str(MANIFEST_PATH.resolve()),
        "source_provenance": manifest.get("provenance", {}),
        "proof_contract": proof_contract,
        "train_summary": train_summary,
        "accepted_meta_symbol_id": meta_id,
        "accepted_record": record,
        "accepted_interface_is_constant": _interface_is_constant(record),
        "verification_results": verification_results,
        "verifier_agreement": verifier_agreement,
        "baseline_no_tsl": baseline_no_tsl_summary,
        "baseline_no_conflict_memory": baseline_no_conflict_summary,
        "baseline_gap": baseline_gap,
        "artifact_files": {
            "graph": str(graph_path.resolve()),
            "telemetry": str(telemetry_path.resolve()),
            "registry": str(registry_path.resolve()),
        },
        "comparison": {
            "baseline_runtime": runtime_row_fields(baseline_no_tsl_summary),
            "densn_runtime": runtime_row_fields(train_summary),
        },
        "checks": {
            "accepted_symbol": meta_id is not None,
            "accepted_interface_non_constant": _interface_is_constant(record) is False,
            "final_psi_zero": train_summary.get("final_psi") is not None
            and float(train_summary.get("final_psi")) <= 0.0,
            "baseline_gap_positive": baseline_gap > 0.0,
            "all_verifiers_passed": bool(verification_results)
            and all(result.get("passed") for result in verification_results),
            "verifier_surfaces_agree": bool(
                verifier_agreement and verifier_agreement.get("all_agree")
            ),
            "real_world_provenance_present": bool(manifest.get("provenance")),
        },
    }
    write_json_artifact(target_dir / "redislock_refresh_summary.json", summary, version=version)
    return summary
