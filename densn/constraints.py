"""Deterministic Boolean constraint engine for the DENSN core."""

from __future__ import annotations

from typing import Callable

from .graph import PersistentGraph
from .records import Constraint, ConstraintEvaluation

Evaluator = Callable[[Constraint, dict[str, bool]], ConstraintEvaluation]


class ConstraintEngine:
    def __init__(self) -> None:
        self._evaluators: dict[str, Evaluator] = {}
        self.register_defaults()

    def register(self, constraint_kind: str, evaluator: Evaluator) -> None:
        self._evaluators[constraint_kind] = evaluator

    def register_defaults(self) -> None:
        self.register("implies", self._eval_implies)
        self.register("xor", self._eval_xor)
        self.register("equivalence", self._eval_equivalence)
        self.register("mutex", self._eval_mutex)
        self.register("observation_lock", self._eval_observation_lock)

    def evaluate_constraint(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        evaluator = self._evaluators.get(constraint.constraint_kind)
        if evaluator is None:
            raise KeyError(f"No evaluator registered for {constraint.constraint_kind}")
        return evaluator(constraint, assignment)

    def evaluate_all(
        self, graph: PersistentGraph, assignment: dict[str, bool]
    ) -> list[ConstraintEvaluation]:
        return [
            self.evaluate_constraint(constraint, assignment)
            for constraint in graph.iter_constraints(active_only=True)
        ]

    def compute_hamiltonian(self, graph: PersistentGraph, assignment: dict[str, bool]) -> float:
        total = 0.0
        for evaluation in self.evaluate_all(graph, assignment):
            if evaluation.violated:
                total += evaluation.weight
        return total

    def compute_local_potentials(
        self, graph: PersistentGraph, assignment: dict[str, bool]
    ) -> dict[str, float]:
        potentials = {symbol_id: 0.0 for symbol_id in graph.symbol_ids()}
        for constraint in graph.iter_constraints(active_only=True):
            evaluation = self.evaluate_constraint(constraint, assignment)
            if not evaluation.violated:
                continue
            for symbol_id in constraint.symbol_ids:
                if symbol_id in potentials:
                    potentials[symbol_id] += constraint.weight
        return potentials

    def compute_forcing_vector(
        self, graph: PersistentGraph, assignment: dict[str, bool]
    ) -> dict[str, float]:
        current_psi = self.compute_hamiltonian(graph, assignment)
        forcing: dict[str, float] = {}
        for symbol in graph.iter_symbols():
            if symbol.locked:
                forcing[symbol.id] = 0.0
                continue
            flipped = dict(assignment)
            flipped[symbol.id] = not flipped[symbol.id]
            flipped_psi = self.compute_hamiltonian(graph, flipped)
            forcing[symbol.id] = current_psi - flipped_psi
        return forcing

    def _lookup(self, assignment: dict[str, bool], symbol_id: str) -> bool:
        if symbol_id not in assignment:
            return False
        return bool(assignment[symbol_id])

    def _eval_implies(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        lhs, rhs = constraint.symbol_ids
        violated = self._lookup(assignment, lhs) and not self._lookup(assignment, rhs)
        return ConstraintEvaluation(
            constraint_id=constraint.id,
            violated=violated,
            satisfied=not violated,
            weight=constraint.weight,
            details={"lhs": lhs, "rhs": rhs},
        )

    def _eval_xor(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        left, right = constraint.symbol_ids
        violated = self._lookup(assignment, left) == self._lookup(assignment, right)
        return ConstraintEvaluation(
            constraint_id=constraint.id,
            violated=violated,
            satisfied=not violated,
            weight=constraint.weight,
            details={"left": left, "right": right},
        )

    def _eval_equivalence(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        left, right = constraint.symbol_ids
        violated = self._lookup(assignment, left) != self._lookup(assignment, right)
        return ConstraintEvaluation(
            constraint_id=constraint.id,
            violated=violated,
            satisfied=not violated,
            weight=constraint.weight,
            details={"left": left, "right": right},
        )

    def _eval_mutex(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        left, right = constraint.symbol_ids
        violated = self._lookup(assignment, left) and self._lookup(assignment, right)
        return ConstraintEvaluation(
            constraint_id=constraint.id,
            violated=violated,
            satisfied=not violated,
            weight=constraint.weight,
            details={"left": left, "right": right},
        )

    def _eval_observation_lock(
        self, constraint: Constraint, assignment: dict[str, bool]
    ) -> ConstraintEvaluation:
        symbol_id = constraint.symbol_ids[0]
        expected = bool(constraint.metadata.get("expected_value", True))
        violated = self._lookup(assignment, symbol_id) != expected
        return ConstraintEvaluation(
            constraint_id=constraint.id,
            violated=violated,
            satisfied=not violated,
            weight=constraint.weight,
            details={"symbol_id": symbol_id, "expected": expected},
        )
