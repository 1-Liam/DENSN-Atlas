"""Cross-family and negative-transfer checks for persistent ontology reuse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_store import artifact_version_info, write_json_artifact
from ..memory import OntologyRegistry
from ..proof_contract import transfer_metrics_summary
from ..system import DENSNSystem
from .formal_protocol import (
    _graph_builder as protocol_graph_builder,
)
from .formal_protocol import (
    _register_protocol_verifier,
    run_formal_protocol_benchmark,
)
from .formal_protocol import (
    heldout_specs as protocol_heldout_specs,
)
from .formal_protocol import (
    reuse_only_config as protocol_reuse_only_config,
)
from .quorum_commit import (
    _graph_builder as quorum_graph_builder,
)
from .quorum_commit import (
    _heldout_claim as quorum_heldout_claim,
)
from .quorum_commit import (
    _register_quorum_verifier,
    negative_transfer_spec,
    run_quorum_commit_benchmark,
)
from .quorum_commit import (
    heldout_specs as quorum_heldout_specs,
)
from .quorum_commit import (
    reuse_only_config as quorum_reuse_only_config,
)

ROOT = Path(__file__).resolve().parents[2]


def _first_accepted_meta_symbol_id(registry: OntologyRegistry) -> str:
    for meta_symbol_id, record in registry.records.items():
        if record.get("status") == "accepted":
            return meta_symbol_id
    raise RuntimeError("Expected at least one accepted meta-symbol in the reloaded registry.")


def _run_cross_family_case(
    *,
    case_id: str,
    registry: OntologyRegistry,
    task,
    graph_builder,
    verifier_registrar,
    config,
) -> dict[str, Any]:
    graph = graph_builder(task, "cross_family")
    system = DENSNSystem(graph, config(), registry=registry)
    verifier_registrar(system)
    reuse_applications = system.apply_reusable_symbols(task_id=task.task_id, graph=graph)
    summary = system.run_until_stable()
    return {
        "case_id": case_id,
        "task_id": task.task_id,
        "reuse_applied": bool(reuse_applications),
        "reuse_application_count": len(reuse_applications),
        "reuse_applications": reuse_applications,
        "summary": summary,
        "negative_transfer_blocked": not reuse_applications,
    }


def _run_negative_transfer_case(
    *,
    registry: OntologyRegistry,
) -> dict[str, Any]:
    task = negative_transfer_spec()
    graph = quorum_graph_builder(task, "negative_transfer")
    system = DENSNSystem(graph, quorum_reuse_only_config(), registry=registry)
    _register_quorum_verifier(system)
    reuse_applications = system.apply_reusable_symbols(task_id=task.task_id, graph=graph)
    summary = system.run_until_stable()

    verification = None
    verifier_failed = None
    if reuse_applications:
        instantiated_id = str(reuse_applications[0]["instantiated_meta_symbol_id"])
        meta_symbol = system.graph.get_node(instantiated_id)
        verification_result = system.verifier.verify(
            quorum_heldout_claim(system, meta_symbol, task)
        )
        verification = verification_result.__dict__
        verifier_failed = bool(verification_result.failed)

    return {
        "task_id": task.task_id,
        "proof_contract": {
            **system.core_contract(),
            "runtime_metrics": summary.get("runtime_metrics", {}),
            "lifecycle_metrics": registry.lifecycle_summary(),
            "transfer_metrics": transfer_metrics_summary(),
        },
        "reuse_applied": bool(reuse_applications),
        "reuse_application_count": len(reuse_applications),
        "reuse_applications": reuse_applications,
        "summary": summary,
        "verification": verification,
        "verifier_failed": verifier_failed,
        "negative_transfer_blocked": bool(reuse_applications) and bool(verifier_failed),
    }


def run_transfer_matrix_benchmark(output_dir: str = "artifacts/phase4") -> dict[str, Any]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase4", root=ROOT)

    run_formal_protocol_benchmark(output_dir="artifacts/phase1")
    run_quorum_commit_benchmark(output_dir="artifacts/phase3")

    protocol_registry_path = ROOT / "artifacts" / "phase1" / "formal_registry.json"
    quorum_registry_path = ROOT / "artifacts" / "phase3" / "quorum_registry.json"
    protocol_registry = OntologyRegistry.load(str(protocol_registry_path))
    quorum_registry = OntologyRegistry.load(str(quorum_registry_path))

    protocol_meta_id = _first_accepted_meta_symbol_id(protocol_registry)
    quorum_meta_id = _first_accepted_meta_symbol_id(quorum_registry)

    cross_family_cases = [
        _run_cross_family_case(
            case_id="protocol_to_quorum",
            registry=protocol_registry,
            task=quorum_heldout_specs()[0],
            graph_builder=quorum_graph_builder,
            verifier_registrar=_register_quorum_verifier,
            config=quorum_reuse_only_config,
        ),
        _run_cross_family_case(
            case_id="quorum_to_protocol",
            registry=quorum_registry,
            task=protocol_heldout_specs()[0],
            graph_builder=protocol_graph_builder,
            verifier_registrar=_register_protocol_verifier,
            config=protocol_reuse_only_config,
        ),
    ]
    negative_transfer = _run_negative_transfer_case(registry=quorum_registry)

    summary = {
        "artifact_version": version,
        "proof_contract": {
            **negative_transfer.get("proof_contract", {}),
            "transfer_metrics": transfer_metrics_summary(
                cross_family_cases=cross_family_cases,
                negative_transfer_case=negative_transfer,
            ),
        },
        "protocol_registry_reloaded_from_disk": True,
        "quorum_registry_reloaded_from_disk": True,
        "protocol_registry_path": str(protocol_registry_path),
        "quorum_registry_path": str(quorum_registry_path),
        "protocol_accepted_meta_symbol_id": protocol_meta_id,
        "quorum_accepted_meta_symbol_id": quorum_meta_id,
        "cross_family_cases": cross_family_cases,
        "negative_transfer_case": negative_transfer,
        "checks": {
            "cross_family_reuse_blocked": all(
                not case["reuse_applied"] for case in cross_family_cases
            ),
            "negative_transfer_verifier_blocked": bool(
                negative_transfer["negative_transfer_blocked"]
            ),
        },
    }
    write_json_artifact(target_dir / "transfer_matrix_summary.json", summary, version=version)
    return summary
