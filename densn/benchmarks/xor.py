"""Synthetic XOR paradox benchmark from the DENSN manuscript."""

from __future__ import annotations

from pathlib import Path

from ..artifact_store import artifact_version_info, snapshot_artifact_file, write_json_artifact
from ..graph import PersistentGraph
from ..proof_contract import transfer_metrics_summary
from ..records import AtomicSymbol, Constraint, Edge, Observation
from ..system import DENSNConfig, DENSNSystem


def build_xor_graph() -> PersistentGraph:
    graph = PersistentGraph()

    s1 = AtomicSymbol(id="S1", name="S1", truth_value=True, locked=True)
    s2 = AtomicSymbol(id="S2", name="S2", truth_value=True, locked=False)
    s3 = AtomicSymbol(id="S3", name="S3", truth_value=True, locked=False)
    graph.add_node(s1)
    graph.add_node(s2)
    graph.add_node(s3)

    obs = Observation(id="OBS_S1", symbol_id="S1", observed_value=True, source="benchmark")
    graph.add_node(obs)

    c_obs = Constraint(
        id="C0",
        constraint_kind="observation_lock",
        symbol_ids=["S1"],
        base_weight=1.0,
        weight=1.0,
        max_weight=16.0,
        metadata={"expected_value": True},
    )
    c1 = Constraint(
        id="C1",
        constraint_kind="implies",
        symbol_ids=["S1", "S2"],
        base_weight=1.0,
        weight=1.0,
        max_weight=16.0,
    )
    c2 = Constraint(
        id="C2",
        constraint_kind="implies",
        symbol_ids=["S2", "S3"],
        base_weight=1.0,
        weight=1.0,
        max_weight=16.0,
    )
    c3 = Constraint(
        id="C3",
        constraint_kind="xor",
        symbol_ids=["S1", "S3"],
        base_weight=1.0,
        weight=1.0,
        max_weight=16.0,
    )
    for constraint in (c_obs, c1, c2, c3):
        graph.add_node(constraint)

    for constraint in (c_obs, c1, c2, c3):
        for symbol_id in constraint.symbol_ids:
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=symbol_id,
                    dst_id=constraint.id,
                    edge_kind="participates_in",
                )
            )
    graph.add_edge(
        Edge(
            id=graph.next_id("edge"),
            src_id=obs.id,
            dst_id="S1",
            edge_kind="supports",
        )
    )
    return graph


def xor_config() -> DENSNConfig:
    return DENSNConfig(
        eta=0.6,
        max_weight_multiplier=16.0,
        frustration_threshold=5.0,
        plateau_window=3,
        plateau_epsilon=1e-9,
        phi_threshold=0.5,
        noise_probability=0.0,
        diffusion_safety_factor=0.95,
        max_cycles=24,
        random_seed=7,
        semantic_verification_threshold=0.1,
    )


def run_xor_benchmark(output_dir: str = "artifacts/phase0") -> dict:
    graph = build_xor_graph()
    system = DENSNSystem(graph=graph, config=xor_config())
    summary = system.run_until_stable()

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase0")
    graph_path = target_dir / "xor_graph.json"
    graph.save(str(graph_path))
    telemetry_path = target_dir / "xor_telemetry.jsonl"
    system.telemetry.flush(str(telemetry_path))
    registry_path = target_dir / "xor_registry.json"
    system.registry.save(str(registry_path))
    artifact_files = {
        "xor_graph": snapshot_artifact_file(graph_path, version=version),
        "xor_telemetry": snapshot_artifact_file(telemetry_path, version=version),
        "xor_registry": snapshot_artifact_file(registry_path, version=version),
    }
    summary_with_version = {
        **summary,
        "artifact_version": version,
        "proof_contract": {
            **system.core_contract(),
            "runtime_metrics": summary.get("runtime_metrics", {}),
            "lifecycle_metrics": system.registry.lifecycle_summary(),
            "transfer_metrics": transfer_metrics_summary(),
        },
    }
    artifact_files["xor_summary"] = write_json_artifact(
        target_dir / "xor_summary.json",
        summary_with_version,
        version=version,
    )
    write_json_artifact(
        target_dir / "xor_artifact_index.json",
        {"artifact_version": version, "files": artifact_files},
        version=version,
    )
    return summary_with_version
