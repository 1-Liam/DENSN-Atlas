"""Spectral diffusion and discrete collapse for the DENSN core."""

from __future__ import annotations

import math
import random

from .constraints import ConstraintEngine
from .graph import PersistentGraph
from .records import CollapseCycle, DiffusionStep, FlipCandidate, MatrixBundle


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(cell * vector[col] for col, cell in enumerate(row)) for row in matrix]


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


class SpectralDynamics:
    def build_incidence_matrix(self, graph: PersistentGraph) -> MatrixBundle:
        constraint_ids = graph.active_constraint_ids()
        symbol_ids = graph.symbol_ids()
        matrix: list[list[float]] = []
        for constraint_id in constraint_ids:
            constraint = graph.get_node(constraint_id)
            row = [1.0 if symbol_id in constraint.symbol_ids else 0.0 for symbol_id in symbol_ids]
            matrix.append(row)
        return MatrixBundle(row_labels=constraint_ids, column_labels=symbol_ids, matrix=matrix)

    def build_laplacian(self, graph: PersistentGraph) -> MatrixBundle:
        incidence = self.build_incidence_matrix(graph)
        symbol_ids = incidence.column_labels
        size = len(symbol_ids)
        laplacian = [[0.0 for _ in range(size)] for _ in range(size)]
        for row_index, constraint_id in enumerate(incidence.row_labels):
            constraint = graph.get_node(constraint_id)
            weight = constraint.weight
            row = incidence.matrix[row_index]
            for i in range(size):
                if row[i] == 0.0:
                    continue
                for j in range(size):
                    if row[j] == 0.0:
                        continue
                    laplacian[i][j] += weight * row[i] * row[j]
        return MatrixBundle(row_labels=symbol_ids, column_labels=symbol_ids, matrix=laplacian)

    def estimate_lambda_max(self, laplacian: MatrixBundle, iterations: int = 32) -> float:
        size = len(laplacian.matrix)
        if size == 0:
            return 0.0
        vector = [1.0 for _ in range(size)]
        norm = vector_norm(vector)
        if norm == 0.0:
            return 0.0
        vector = [value / norm for value in vector]
        eigenvalue = 0.0
        for _ in range(iterations):
            candidate = matvec(laplacian.matrix, vector)
            norm = vector_norm(candidate)
            if norm == 0.0:
                return 0.0
            vector = [value / norm for value in candidate]
            eigenvalue = dot(vector, matvec(laplacian.matrix, vector))
        return eigenvalue

    def initialize_kappa(self, lambda_max: float, safety_factor: float = 0.95) -> float:
        if lambda_max <= 0.0:
            return 1.0
        return (2.0 / lambda_max) * safety_factor

    def diffuse(
        self,
        phi: dict[str, float],
        laplacian: MatrixBundle,
        forcing: dict[str, float],
        kappa: float,
        lambda_max: float,
    ) -> DiffusionStep:
        labels = laplacian.row_labels
        vector = [phi[label] for label in labels]
        forcing_vector = [forcing[label] for label in labels]
        lphi = matvec(laplacian.matrix, vector)
        next_vector = [
            vector[index] - kappa * lphi[index] + forcing_vector[index]
            for index in range(len(vector))
        ]
        return DiffusionStep(
            phi_before=dict(phi),
            phi_after={label: next_vector[index] for index, label in enumerate(labels)},
            kappa=kappa,
            lambda_max=lambda_max,
        )

    def quadratic_energy(self, phi: dict[str, float], laplacian: MatrixBundle) -> float:
        labels = laplacian.row_labels
        vector = [phi[label] for label in labels]
        lphi = matvec(laplacian.matrix, vector)
        return dot(vector, lphi)


class CollapseEngine:
    def __init__(
        self,
        constraint_engine: ConstraintEngine,
        phi_threshold: float = 0.1,
        noise_probability: float = 0.1,
        seed: int = 7,
    ) -> None:
        self.constraint_engine = constraint_engine
        self.phi_threshold = phi_threshold
        self.noise_probability = noise_probability
        self.random = random.Random(seed)

    def score_flips(
        self,
        graph: PersistentGraph,
        assignment: dict[str, bool],
        phi: dict[str, float],
    ) -> list[FlipCandidate]:
        current_psi = self.constraint_engine.compute_hamiltonian(graph, assignment)
        candidates: list[FlipCandidate] = []
        for symbol in graph.iter_symbols():
            flipped_assignment = dict(assignment)
            flipped_assignment[symbol.id] = not flipped_assignment[symbol.id]
            flipped_psi = self.constraint_engine.compute_hamiltonian(graph, flipped_assignment)
            candidates.append(
                FlipCandidate(
                    symbol_id=symbol.id,
                    phi=phi.get(symbol.id, 0.0),
                    delta_psi=flipped_psi - current_psi,
                    locked=bool(symbol.locked),
                )
            )
        candidates.sort(key=lambda item: abs(item.phi), reverse=True)
        return candidates

    def apply_greedy_step(
        self,
        graph: PersistentGraph,
        assignment: dict[str, bool],
        candidates: list[FlipCandidate],
    ) -> tuple[dict[str, bool], list[str]]:
        next_assignment = dict(assignment)
        flipped: list[str] = []
        for candidate in candidates:
            if candidate.locked or abs(candidate.phi) < self.phi_threshold:
                continue
            if candidate.delta_psi < 0.0:
                next_assignment[candidate.symbol_id] = not next_assignment[candidate.symbol_id]
                flipped.append(candidate.symbol_id)
        return next_assignment, flipped

    def apply_noisy_step(
        self,
        graph: PersistentGraph,
        assignment: dict[str, bool],
        candidates: list[FlipCandidate],
    ) -> tuple[dict[str, bool], list[str]]:
        next_assignment = dict(assignment)
        flipped: list[str] = []
        for candidate in candidates:
            if candidate.locked or abs(candidate.phi) < self.phi_threshold:
                continue
            if self.random.random() < self.noise_probability:
                next_assignment[candidate.symbol_id] = not next_assignment[candidate.symbol_id]
                flipped.append(candidate.symbol_id)
        return next_assignment, flipped

    def run_cycle(
        self,
        graph: PersistentGraph,
        assignment: dict[str, bool],
        phi: dict[str, float],
    ) -> CollapseCycle:
        psi_before = self.constraint_engine.compute_hamiltonian(graph, assignment)
        candidates = self.score_flips(graph, assignment, phi)
        next_assignment, flipped = self.apply_greedy_step(graph, assignment, candidates)
        method = "greedy"
        if not flipped:
            next_assignment, flipped = self.apply_noisy_step(graph, assignment, candidates)
            method = "noisy" if flipped else "stalled"
        graph.set_assignment(next_assignment)
        psi_after = self.constraint_engine.compute_hamiltonian(graph, graph.assignment())
        return CollapseCycle(
            flipped_symbol_ids=flipped,
            method=method,
            escaped=psi_after < psi_before,
            psi_before=psi_before,
            psi_after=psi_after,
        )

    def random_restart(self, graph: PersistentGraph) -> dict[str, bool]:
        assignment = graph.assignment()
        for symbol in graph.iter_symbols():
            if symbol.locked:
                continue
            assignment[symbol.id] = bool(self.random.randint(0, 1))
        graph.set_assignment(assignment)
        return assignment
