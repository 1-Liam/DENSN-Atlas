"""Legacy compatibility wrapper for the artifact-backed formal protocol benchmark."""

from __future__ import annotations

from pathlib import Path

from .formal_protocol import (
    build_protocol_graph_from_manifest,
    run_formal_protocol_benchmark,
    train_manifest_path,
)


def build_window_graph(prefix: str, payload_count: int = 1):
    return build_protocol_graph_from_manifest(
        Path(train_manifest_path()),
        prefix=prefix,
        write_count=payload_count,
    )


def run_formal_window_benchmark(output_dir: str = "artifacts/phase1"):
    return run_formal_protocol_benchmark(output_dir=output_dir)
