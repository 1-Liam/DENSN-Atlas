"""Topological Structure Learning for DENSN."""

from __future__ import annotations

import itertools
from collections import deque

from .constraints import ConstraintEngine
from .graph import PersistentGraph
from .records import (
    ClusterCandidate,
    Constraint,
    Edge,
    InterfaceSynthesisResult,
    MetaSymbol,
    MetaSymbolProposal,
    TopologyRevision,
)


class TSLEngine:
    def __init__(
        self,
        constraint_engine: ConstraintEngine,
        frustration_threshold: float = 8.0,
        persistence_trigger: float = 6.0,
        recurrence_trigger: int = 3,
        proposal_support_threshold: float = 1.0,
        proposal_threshold_floor_ratio: float = 0.75,
        proposal_support_discount_scale: float = 0.2,
    ) -> None:
        self.constraint_engine = constraint_engine
        self.frustration_threshold = frustration_threshold
        self.persistence_trigger = persistence_trigger
        self.recurrence_trigger = recurrence_trigger
        self.proposal_support_threshold = proposal_support_threshold
        self.proposal_threshold_floor_ratio = proposal_threshold_floor_ratio
        self.proposal_support_discount_scale = proposal_support_discount_scale

    def should_trigger_pathway_a(self, metrics: dict[str, float | bool]) -> bool:
        return (
            bool(metrics.get("plateaued"))
            and float(metrics.get("psi", 0.0)) < self.frustration_threshold
        )

    def should_trigger_pathway_b(self, metrics: dict[str, float | bool]) -> bool:
        psi = float(metrics.get("psi", 0.0))
        proposal_support = float(metrics.get("proposal_support", 0.0))
        effective_threshold = self.frustration_threshold
        if proposal_support >= self.proposal_support_threshold:
            discounted = self.frustration_threshold - (
                proposal_support * self.proposal_support_discount_scale
            )
            floor = self.frustration_threshold * self.proposal_threshold_floor_ratio
            effective_threshold = max(floor, discounted)
        psi_high = psi >= effective_threshold
        plateaued = bool(metrics.get("plateaued"))
        persistent = float(metrics.get("top_hotspot_persistence", 0.0)) >= self.persistence_trigger
        recurrent = int(metrics.get("hotspot_recurrence", 0)) >= self.recurrence_trigger
        proposal_supported = proposal_support >= self.proposal_support_threshold
        return psi_high and (plateaued or persistent or recurrent or proposal_supported)

    def find_clusters(
        self,
        graph: PersistentGraph,
        hotspot_scores: list,
        mode: str,
    ) -> list[ClusterCandidate]:
        clusters: list[ClusterCandidate] = []
        if mode == "FRUSTRATION":
            for hotspot in hotspot_scores:
                clusters.append(
                    ClusterCandidate(
                        cluster_id=hotspot.cluster_id,
                        symbol_ids=hotspot.symbol_ids,
                        constraint_ids=hotspot.constraint_ids,
                        score=hotspot.rank_score,
                        mode=mode,
                    )
                )
        else:
            assignment = graph.assignment()
            coherent_constraints = [
                constraint
                for constraint in graph.iter_constraints(active_only=True)
                if not self.constraint_engine.evaluate_constraint(constraint, assignment).violated
            ]
            coherent_by_id = {constraint.id: constraint for constraint in coherent_constraints}
            visited: set[str] = set()
            component_index = 0

            for constraint in coherent_constraints:
                if constraint.id in visited:
                    continue
                queue = deque([constraint.id])
                coherent_constraint_ids: set[str] = set()
                coherent_symbol_ids: set[str] = set()

                while queue:
                    current_constraint_id = queue.popleft()
                    if current_constraint_id in visited:
                        continue
                    visited.add(current_constraint_id)
                    current_constraint = coherent_by_id.get(current_constraint_id)
                    if current_constraint is None:
                        continue
                    coherent_constraint_ids.add(current_constraint_id)
                    for symbol_id in current_constraint.symbol_ids:
                        coherent_symbol_ids.add(symbol_id)
                        for neighbor_constraint in coherent_constraints:
                            if (
                                neighbor_constraint.id not in visited
                                and symbol_id in neighbor_constraint.symbol_ids
                            ):
                                queue.append(neighbor_constraint.id)

                if len(coherent_symbol_ids) < 2 or not coherent_constraint_ids:
                    continue
                component_index += 1
                clusters.append(
                    ClusterCandidate(
                        cluster_id=f"coherent_{component_index}",
                        symbol_ids=sorted(coherent_symbol_ids),
                        constraint_ids=sorted(coherent_constraint_ids),
                        score=float(len(coherent_constraint_ids)),
                        mode=mode,
                    )
                )
            clusters.sort(
                key=lambda cluster: (cluster.score, len(cluster.symbol_ids)), reverse=True
            )
        return clusters

    def compute_markov_blanket(
        self,
        graph: PersistentGraph,
        cluster_symbol_ids: list[str],
        cluster_constraint_ids: list[str],
    ) -> list[str]:
        cluster_symbols = set(cluster_symbol_ids)
        cluster_constraints = set(cluster_constraint_ids)
        blanket: set[str] = set()
        for constraint in graph.iter_constraints(active_only=True):
            if constraint.id in cluster_constraints:
                continue
            if any(symbol_id in cluster_symbols for symbol_id in constraint.symbol_ids):
                for symbol_id in constraint.symbol_ids:
                    if symbol_id not in cluster_symbols:
                        blanket.add(symbol_id)
        return sorted(blanket)

    def synthesize_interface(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        blanket_symbol_ids: list[str],
    ) -> InterfaceSynthesisResult:
        if len(blanket_symbol_ids) <= 6:
            return self._exact_interface(graph, cluster, blanket_symbol_ids)
        return self._approximate_interface(graph, cluster, blanket_symbol_ids)

    def _exact_interface(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        blanket_symbol_ids: list[str],
    ) -> InterfaceSynthesisResult:
        truth_table, satisfiable_cases = self._interface_truth_table(
            graph,
            cluster,
            blanket_symbol_ids,
        )
        notes = "exact_boundary_projection_interface"
        return InterfaceSynthesisResult(
            mode="exact",
            blanket_symbol_ids=blanket_symbol_ids,
            truth_table=truth_table,
            satisfiable_cases=satisfiable_cases,
            total_cases=len(truth_table),
            notes=notes,
        )

    def _interface_truth_table(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        blanket_symbol_ids: list[str],
        fixed_assignments: dict[str, bool] | None = None,
    ) -> tuple[dict[str, bool], int]:
        assignment = graph.assignment()
        fixed_assignments = fixed_assignments or {}
        interface_constraints = self._interface_constraints(
            graph,
            cluster,
            blanket_symbol_ids,
        )
        free_symbol_ids = [
            symbol_id
            for symbol_id in cluster.symbol_ids
            if symbol_id not in blanket_symbol_ids and not graph.get_node(symbol_id).locked
        ]
        truth_table: dict[str, bool] = {}
        satisfiable_cases = 0

        blanket_assignments = list(itertools.product([False, True], repeat=len(blanket_symbol_ids)))
        if not blanket_assignments:
            blanket_assignments = [tuple()]

        for values in blanket_assignments:
            key = ",".join(
                f"{symbol_id}={int(value)}" for symbol_id, value in zip(blanket_symbol_ids, values)
            )
            working_assignment = dict(assignment)
            working_assignment.update(fixed_assignments)
            for symbol_id, value in zip(blanket_symbol_ids, values):
                working_assignment[symbol_id] = value
            satisfiable = False
            internal_assignments = list(
                itertools.product([False, True], repeat=len(free_symbol_ids))
            )
            if not internal_assignments:
                internal_assignments = [tuple()]
            for free_values in internal_assignments:
                for symbol_id, value in zip(free_symbol_ids, free_values):
                    working_assignment[symbol_id] = value
                if self._cluster_satisfied(interface_constraints, working_assignment):
                    satisfiable = True
                    break
            truth_table[key or "()"] = satisfiable
            if satisfiable:
                satisfiable_cases += 1

        return truth_table, satisfiable_cases

    def _interface_constraints(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        blanket_symbol_ids: list[str],
    ) -> list[Constraint]:
        cluster_symbol_ids = set(cluster.symbol_ids)
        blanket_set = set(blanket_symbol_ids)
        local_symbol_ids = cluster_symbol_ids | blanket_set
        boundary_constraints: list[Constraint] = []
        for constraint in graph.iter_constraints(active_only=True):
            if constraint.id in cluster.constraint_ids:
                continue
            symbol_set = set(constraint.symbol_ids)
            if not (symbol_set & cluster_symbol_ids):
                continue
            if not symbol_set <= local_symbol_ids:
                continue
            boundary_constraints.append(constraint)
        if boundary_constraints:
            return boundary_constraints
        return [
            graph.get_node(constraint_id)
            for constraint_id in cluster.constraint_ids
            if constraint_id in graph.nodes
        ]

    def _approximate_interface(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        blanket_symbol_ids: list[str],
    ) -> InterfaceSynthesisResult:
        assignment = graph.assignment()
        influence_scores: dict[str, int] = {}
        for symbol_id in blanket_symbol_ids:
            influence_scores[symbol_id] = 0
            for constraint in graph.iter_constraints(active_only=True):
                if symbol_id in constraint.symbol_ids:
                    influence_scores[symbol_id] += 1

        representative_blanket = sorted(
            blanket_symbol_ids,
            key=lambda symbol_id: (-influence_scores.get(symbol_id, 0), symbol_id),
        )[:6]
        fixed_assignments = {
            symbol_id: bool(assignment.get(symbol_id, False))
            for symbol_id in blanket_symbol_ids
            if symbol_id not in representative_blanket
        }
        truth_table, satisfiable_cases = self._interface_truth_table(
            graph,
            cluster,
            representative_blanket,
            fixed_assignments=fixed_assignments,
        )
        return InterfaceSynthesisResult(
            mode="approximate",
            blanket_symbol_ids=representative_blanket,
            truth_table=truth_table,
            satisfiable_cases=satisfiable_cases,
            total_cases=len(truth_table),
            notes=(
                f"approximate_projected_interface_for_{cluster.cluster_id};"
                f"representative_inputs={representative_blanket};"
                f"fixed_inputs={sorted(fixed_assignments)}"
            ),
        )

    def _cluster_satisfied(
        self, constraints: list[Constraint], assignment: dict[str, bool]
    ) -> bool:
        for constraint in constraints:
            evaluation = self.constraint_engine.evaluate_constraint(constraint, assignment)
            if evaluation.violated:
                return False
        return True

    def propose_meta_symbol(
        self,
        graph: PersistentGraph,
        cluster: ClusterCandidate,
        interface_result: InterfaceSynthesisResult,
        pathway: str,
    ) -> MetaSymbolProposal:
        meta_id = graph.next_id("meta")
        meta_symbol = MetaSymbol(
            id=meta_id,
            structural_name=meta_id.upper(),
            interface_kind=interface_result.mode,
            interface_inputs=list(interface_result.blanket_symbol_ids),
            interface_definition={
                "truth_table": interface_result.truth_table,
                "notes": interface_result.notes,
            },
            parent_cluster_symbol_ids=list(cluster.symbol_ids),
            markov_blanket_symbol_ids=list(interface_result.blanket_symbol_ids),
            metadata={
                "cluster_id": cluster.cluster_id,
                "tsl_pathway": pathway,
            },
        )
        return MetaSymbolProposal(
            meta_symbol=meta_symbol,
            cluster=cluster,
            interface_result=interface_result,
        )

    def apply_abstraction(
        self,
        graph: PersistentGraph,
        proposal: MetaSymbolProposal,
    ) -> TopologyRevision:
        meta_symbol = proposal.meta_symbol
        graph.add_node(meta_symbol)
        for symbol_id in proposal.cluster.symbol_ids:
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=meta_symbol.id,
                    dst_id=symbol_id,
                    edge_kind="abstracts",
                )
            )
        retired_constraint_ids: list[str] = []
        for constraint_id in proposal.cluster.constraint_ids:
            if constraint_id not in graph.nodes:
                continue
            constraint = graph.get_node(constraint_id)
            constraint.active = False
            constraint.metadata["abstracted_by"] = meta_symbol.id
            retired_constraint_ids.append(constraint_id)
        return TopologyRevision(
            meta_symbol_id=meta_symbol.id,
            retired_constraint_ids=retired_constraint_ids,
            cluster_symbol_ids=list(proposal.cluster.symbol_ids),
            cluster_constraint_ids=list(proposal.cluster.constraint_ids),
        )

    def local_reset(self, graph: PersistentGraph, revision: TopologyRevision) -> None:
        for symbol_id in revision.cluster_symbol_ids:
            node = graph.get_node(symbol_id)
            if getattr(node, "locked", False):
                continue
            if hasattr(node, "truth_value"):
                node.truth_value = False

    def rollback_abstraction(self, graph: PersistentGraph, revision: TopologyRevision) -> None:
        for constraint_id in revision.retired_constraint_ids:
            if constraint_id not in graph.nodes:
                continue
            constraint = graph.get_node(constraint_id)
            constraint.active = True
            constraint.metadata.pop("abstracted_by", None)
        graph.remove_node(revision.meta_symbol_id)
