"""Exercise the proposal quarantine on real protocol artifacts without ontology authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact
from densn.benchmarks.formal_protocol import build_protocol_graph_from_manifest, train_manifest_path
from densn.proposal_review import ArtifactStructuralProposalReviewer
from densn.system import DENSNSystem
from densn.transformer import (
    ArtifactHeuristicTransformerAdapter,
    build_transformer_adapter_from_env,
)


def main() -> None:
    graph = build_protocol_graph_from_manifest(
        train_manifest_path(), prefix="PROPOSAL_AUDIT", write_count=2
    )
    system = DENSNSystem(graph)
    adapter = build_transformer_adapter_from_env(fallback=ArtifactHeuristicTransformerAdapter())
    if adapter is None:
        raise RuntimeError("No transformer adapter is available.")
    system.set_transformer_adapter(adapter)
    system.register_proposal_reviewer(ArtifactStructuralProposalReviewer())
    output_dir = ROOT / "artifacts" / "phase2"
    output_dir.mkdir(parents=True, exist_ok=True)
    version = artifact_version_info("phase2", root=ROOT)

    before = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
    proposal_ids = system.transformer_propose(
        artifacts=[{"id": "protocol_manifest_train", "manifest_path": str(train_manifest_path())}],
        context={
            "manifest_paths": [str(train_manifest_path())],
            "evidence_query": "guard protocol invariant",
        },
        task_id="proposal_audit",
    )
    system.review_pending_proposals(
        artifacts=[{"id": "protocol_manifest_train", "manifest_path": str(train_manifest_path())}],
        context={
            "manifest_paths": [str(train_manifest_path())],
            "evidence_query": "guard protocol invariant",
        },
    )

    after = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
    summary = {
        "artifact_version": version,
        "adapter": adapter.__class__.__name__,
        "proposal_ids": proposal_ids,
        "proposal_summary": system.proposal_summary(),
        "telemetry_summary": system.telemetry.summary(),
        "graph_before": before,
        "graph_after": after,
        "ontology_mutated_directly": before != after,
    }
    write_json_artifact(output_dir / "proposal_audit_summary.json", summary, version=version)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
