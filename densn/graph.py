"""Persistent typed graph storage for the DENSN substrate."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .records import (
    NODE_TYPE_MAP,
    AtomicSymbol,
    Constraint,
    Edge,
    MetaSymbol,
    utc_now,
)


class PersistentGraph:
    """Typed graph with inspectable JSON persistence."""

    def __init__(self, storage_path: str | None = None) -> None:
        self.storage_path = storage_path
        self.graph_version = "0.1.0"
        self.created_at = utc_now()
        self.updated_at = utc_now()
        self.nodes: dict[str, Any] = {}
        self.edges: dict[str, Edge] = {}

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def next_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:8]}"

    def add_node(self, node: Any) -> str:
        self.nodes[node.id] = node
        self._touch()
        return node.id

    def add_edge(self, edge: Edge) -> str:
        self.edges[edge.id] = edge
        self._touch()
        return edge.id

    def remove_edge(self, edge_id: str) -> None:
        if edge_id in self.edges:
            del self.edges[edge_id]
            self._touch()

    def remove_node(self, node_id: str) -> None:
        if node_id in self.nodes:
            del self.nodes[node_id]
        edge_ids = [
            edge_id
            for edge_id, edge in self.edges.items()
            if edge.src_id == node_id or edge.dst_id == node_id
        ]
        for edge_id in edge_ids:
            del self.edges[edge_id]
        self._touch()

    def get_node(self, node_id: str) -> Any:
        return self.nodes[node_id]

    def get_edge(self, edge_id: str) -> Edge:
        return self.edges[edge_id]

    def iter_nodes(self, node_type: str | None = None) -> Iterable[Any]:
        for node in self.nodes.values():
            if node_type is None or node.node_type == node_type:
                yield node

    def iter_edges(self, edge_kind: str | None = None) -> Iterable[Edge]:
        for edge in self.edges.values():
            if edge_kind is None or edge.edge_kind == edge_kind:
                yield edge

    def iter_symbols(self) -> Iterable[AtomicSymbol | MetaSymbol]:
        for node in self.nodes.values():
            if node.node_type in {"AtomicSymbol", "MetaSymbol"}:
                yield node

    def iter_constraints(self, active_only: bool = True) -> Iterable[Constraint]:
        for node in self.iter_nodes("Constraint"):
            if not active_only or node.active:
                yield node

    def neighbors(self, node_id: str, edge_kind: str | None = None) -> list[str]:
        neighbor_ids: list[str] = []
        for edge in self.edges.values():
            if edge_kind is not None and edge.edge_kind != edge_kind:
                continue
            if edge.src_id == node_id:
                neighbor_ids.append(edge.dst_id)
            elif edge.dst_id == node_id:
                neighbor_ids.append(edge.src_id)
        return neighbor_ids

    def subgraph(self, node_ids: Iterable[str]) -> "PersistentGraph":
        selected = set(node_ids)
        sub = PersistentGraph(storage_path=None)
        for node_id in selected:
            if node_id in self.nodes:
                sub.nodes[node_id] = self.nodes[node_id]
        for edge_id, edge in self.edges.items():
            if edge.src_id in selected and edge.dst_id in selected:
                sub.edges[edge_id] = edge
        return sub

    def symbol_ids(self) -> list[str]:
        return sorted(node.id for node in self.iter_symbols())

    def assignment(self) -> dict[str, bool]:
        return {node.id: bool(node.truth_value) for node in self.iter_symbols()}

    def set_assignment(self, assignment: dict[str, bool]) -> None:
        for symbol in self.iter_symbols():
            if symbol.id in assignment and not symbol.locked:
                symbol.truth_value = bool(assignment[symbol.id])
                symbol.updated_at = utc_now()
        self._touch()

    def active_constraint_ids(self) -> list[str]:
        return sorted(constraint.id for constraint in self.iter_constraints(active_only=True))

    def snapshot(self) -> dict[str, Any]:
        return {
            "graph_version": self.graph_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges.values()],
        }

    def save(self, path: str | None = None) -> None:
        target = Path(path or self.storage_path or "graph.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "PersistentGraph":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        graph = cls(storage_path=path)
        graph.graph_version = raw["graph_version"]
        graph.created_at = raw["created_at"]
        graph.updated_at = raw["updated_at"]
        for node_data in raw["nodes"]:
            node_type = node_data.pop("node_type")
            node_cls = NODE_TYPE_MAP[node_type]
            node = node_cls(**node_data)
            graph.nodes[node.id] = node
        for edge_data in raw["edges"]:
            graph.edges[edge_data["id"]] = Edge(**edge_data)
        return graph
