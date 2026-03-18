"""Conflict cache and hotspot ranking."""

from __future__ import annotations

from collections import deque

from .graph import PersistentGraph
from .records import Constraint, ConstraintEvaluation, HotspotScore


class ConflictCache:
    def __init__(
        self,
        eta: float = 0.6,
        max_multiplier: float = 16.0,
        hotspot_persistence_bias: float = 0.5,
    ) -> None:
        self.eta = eta
        self.max_multiplier = max_multiplier
        self.hotspot_persistence_bias = hotspot_persistence_bias
        self.persistence: dict[str, int] = {}
        self.last_violated: dict[str, bool] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def record(self, graph: PersistentGraph, evaluations: list[ConstraintEvaluation]) -> None:
        constraints = {
            constraint.id: constraint for constraint in graph.iter_constraints(active_only=False)
        }
        for evaluation in evaluations:
            constraint = constraints[evaluation.constraint_id]
            current = self.persistence.get(constraint.id, 0)
            if evaluation.violated:
                current += 1
                constraint.failure_count += 1
            else:
                current = 0
            self.persistence[constraint.id] = current
            constraint.persistence = current
            constraint.weight = self.get_weight(constraint)
            self.last_violated[constraint.id] = evaluation.violated

    def get_persistence(self, constraint_id: str) -> int:
        return self.persistence.get(constraint_id, 0)

    def get_weight(self, constraint: Constraint) -> float:
        raw = constraint.base_weight * (1.0 + self.eta * self.persistence.get(constraint.id, 0))
        maximum = constraint.base_weight * self.max_multiplier
        return min(raw, maximum)

    def reset_local(self, constraints: list[Constraint]) -> None:
        for constraint in constraints:
            self.persistence[constraint.id] = 0
            constraint.persistence = 0
            constraint.weight = constraint.base_weight

    def rank_hotspots(self, graph: PersistentGraph) -> list[HotspotScore]:
        active_constraints = {
            constraint.id: constraint for constraint in graph.iter_constraints(active_only=True)
        }
        violated_constraint_ids = [
            constraint_id
            for constraint_id, violated in self.last_violated.items()
            if violated and constraint_id in active_constraints
        ]
        visited: set[str] = set()
        hotspots: list[HotspotScore] = []

        for constraint_id in violated_constraint_ids:
            if constraint_id in visited:
                continue
            queue = deque([constraint_id])
            component_constraint_ids: set[str] = set()
            component_symbol_ids: set[str] = set()

            while queue:
                current_constraint_id = queue.popleft()
                if current_constraint_id in visited:
                    continue
                visited.add(current_constraint_id)
                if current_constraint_id not in active_constraints:
                    continue
                constraint = active_constraints[current_constraint_id]
                component_constraint_ids.add(current_constraint_id)
                for symbol_id in constraint.symbol_ids:
                    component_symbol_ids.add(symbol_id)
                    for neighbor_constraint in graph.iter_constraints(active_only=True):
                        if (
                            neighbor_constraint.id not in visited
                            and symbol_id in neighbor_constraint.symbol_ids
                            and self.last_violated.get(neighbor_constraint.id, False)
                        ):
                            queue.append(neighbor_constraint.id)

            tension = sum(active_constraints[cid].weight for cid in component_constraint_ids)
            persistence_mass = float(
                sum(self.persistence.get(cid, 0) for cid in component_constraint_ids)
            )
            hotspots.append(
                HotspotScore(
                    cluster_id=f"hotspot_{len(hotspots) + 1}",
                    constraint_ids=sorted(component_constraint_ids),
                    symbol_ids=sorted(component_symbol_ids),
                    tension=tension,
                    persistence_mass=persistence_mass,
                    rank_score=tension + self.hotspot_persistence_bias * persistence_mass,
                )
            )

        hotspots.sort(key=lambda item: item.rank_score, reverse=True)
        return hotspots

    def stats(self) -> dict[str, float]:
        return {
            "cache_hits": float(self.cache_hits),
            "cache_misses": float(self.cache_misses),
            "tracked_constraints": float(len(self.persistence)),
        }
