"""DENSN system orchestration."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from .cache import ConflictCache
from .constraints import ConstraintEngine
from .dynamics import CollapseEngine, SpectralDynamics
from .graph import PersistentGraph
from .memory import OntologyRegistry
from .proof_contract import ALLOWED_CORE_MODES, CORE_API_VERSION, proposal_adapter_summary
from .proposal_review import ProposalReviewer
from .proposals import ProposalQuarantine
from .records import (
    Edge,
    Evidence,
    MetaSymbol,
    ProposalRecord,
    VerificationResult,
    VerifierArtifact,
    utc_now,
)
from .semantic import SemanticBridge
from .telemetry import TelemetryRecorder
from .transformer import TransformerAdapter
from .tsl import TSLEngine
from .verifier import VerifierBus

CandidateEvaluator = Callable[["DENSNSystem", dict[str, Any]], dict[str, Any]]


@dataclass
class DENSNConfig:
    core_mode: str = "core_frozen"
    expected_core_api_version: str = CORE_API_VERSION
    migration_note: str | None = None
    eta: float = 0.6
    max_weight_multiplier: float = 16.0
    frustration_threshold: float = 8.0
    plateau_window: int = 3
    plateau_epsilon: float = 1e-6
    phi_threshold: float = 0.1
    noise_probability: float = 0.1
    diffusion_safety_factor: float = 0.95
    max_cycles: int = 24
    random_seed: int = 7
    semantic_verification_threshold: float = 0.1
    hotspot_persistence_bias: float = 0.5
    pathway_b_persistence_threshold: float = 6.0
    hotspot_recurrence_threshold: int = 3
    require_verifier_for_admission: bool = False
    require_reuse_for_admission: bool = False
    require_novelty_for_admission: bool = True
    min_heldout_contradiction_gain: float = 0.0
    max_complexity_penalty: float = 8.0
    max_failure_count_before_retirement: int = 3
    min_reuse_successes_before_retirement: int = 1
    artifacts_dir: str = "artifacts"
    candidate_labels: list[str] = field(default_factory=list)
    proposal_support_threshold: float = 1.0
    proposal_threshold_floor_ratio: float = 0.75
    proposal_support_discount_scale: float = 0.2


class DENSNSystem:
    def __init__(
        self,
        graph: PersistentGraph,
        config: DENSNConfig | None = None,
        registry: OntologyRegistry | None = None,
    ) -> None:
        self.graph = graph
        self.config = config or DENSNConfig()
        self._validate_core_contract()
        self.telemetry = TelemetryRecorder()
        self.constraint_engine = ConstraintEngine()
        self.conflict_cache = ConflictCache(
            eta=self.config.eta,
            max_multiplier=self.config.max_weight_multiplier,
            hotspot_persistence_bias=self.config.hotspot_persistence_bias,
        )
        self.spectral = SpectralDynamics()
        self.collapse = CollapseEngine(
            constraint_engine=self.constraint_engine,
            phi_threshold=self.config.phi_threshold,
            noise_probability=self.config.noise_probability,
            seed=self.config.random_seed,
        )
        self.tsl = TSLEngine(
            constraint_engine=self.constraint_engine,
            frustration_threshold=self.config.frustration_threshold,
            persistence_trigger=self.config.pathway_b_persistence_threshold,
            recurrence_trigger=self.config.hotspot_recurrence_threshold,
            proposal_support_threshold=self.config.proposal_support_threshold,
            proposal_threshold_floor_ratio=self.config.proposal_threshold_floor_ratio,
            proposal_support_discount_scale=self.config.proposal_support_discount_scale,
        )
        self.semantic = SemanticBridge(threshold=self.config.semantic_verification_threshold)
        self.verifier = VerifierBus()
        self.registry = registry or OntologyRegistry()
        self.proposal_quarantine = ProposalQuarantine()
        self.transformer_adapter: TransformerAdapter | None = None
        self.proposal_reviewer: ProposalReviewer | None = None
        self.proposal_session: dict[str, Any] | None = None
        self.psi_history: list[float] = []
        self.hotspot_history: list[str] = []
        self.candidate_evaluator: CandidateEvaluator | None = None

    def _validate_core_contract(self) -> None:
        if self.config.core_mode not in ALLOWED_CORE_MODES:
            raise ValueError(
                f"Unsupported core mode {self.config.core_mode!r}. "
                f"Expected one of {sorted(ALLOWED_CORE_MODES)}."
            )
        if self.config.core_mode != "core_frozen":
            return
        expected = self.config.expected_core_api_version
        if expected != CORE_API_VERSION and not self.config.migration_note:
            raise RuntimeError(
                "core_frozen mode refused structural API drift because the expected core "
                f"API version {expected!r} does not match {CORE_API_VERSION!r} and no "
                "migration note was supplied."
            )

    def core_contract(self) -> dict[str, Any]:
        return {
            "core_mode": self.config.core_mode,
            "core_api_version": CORE_API_VERSION,
            "expected_core_api_version": self.config.expected_core_api_version,
            "migration_note": self.config.migration_note,
            "proposal_adapter": proposal_adapter_summary(self.transformer_adapter),
            "verifier_stack": self.verifier.describe(),
        }

    def register_candidate_evaluator(self, evaluator: CandidateEvaluator) -> None:
        self.candidate_evaluator = evaluator

    def set_transformer_adapter(self, adapter: TransformerAdapter) -> None:
        self.transformer_adapter = adapter

    def register_proposal_reviewer(self, reviewer: ProposalReviewer) -> None:
        self.proposal_reviewer = reviewer

    def configure_proposal_session(
        self,
        *,
        artifacts: list[dict],
        context: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.proposal_session = {
            "artifacts": list(artifacts),
            "context": dict(context or {}),
            "task_id": task_id,
            "submitted": False,
        }

    def submit_proposals(
        self, proposals: list[ProposalRecord], task_id: str | None = None
    ) -> list[str]:
        proposal_ids = self.proposal_quarantine.submit_many(proposals)
        for proposal_id in proposal_ids:
            proposal = self.proposal_quarantine.get(proposal_id)
            self.telemetry.record_step(
                {
                    "event_type": "proposal_submitted",
                    "proposal_id": proposal_id,
                    "proposal_type": proposal.proposal_type,
                    "source": proposal.source,
                    "task_id": task_id or proposal.task_id,
                }
            )
        return proposal_ids

    def transformer_propose(
        self,
        artifacts: list[dict],
        context: dict | None = None,
        task_id: str | None = None,
    ) -> list[str]:
        if self.transformer_adapter is None:
            return []
        context = context or {}
        proposals: list[ProposalRecord] = []
        proposals.extend(self.transformer_adapter.extract_atoms(artifacts, task_id=task_id))
        proposals.extend(self.transformer_adapter.extract_constraints(artifacts, task_id=task_id))
        proposals.extend(
            self.transformer_adapter.propose_hidden_variables(context, task_id=task_id)
        )
        proposals.extend(self.transformer_adapter.propose_labels(context, task_id=task_id))
        proposals.extend(self.transformer_adapter.generate_tests({}, context, task_id=task_id))
        query = str(context.get("evidence_query", ""))
        if query:
            proposals.extend(self.transformer_adapter.retrieve_evidence(query, task_id=task_id))
        return self.submit_proposals(proposals, task_id=task_id)

    def review_proposal(self, proposal_id: str, status: str, reason: str) -> ProposalRecord:
        proposal = self.proposal_quarantine.review(proposal_id, status=status, reason=reason)
        self.telemetry.record_step(
            {
                "event_type": "proposal_reviewed",
                "proposal_id": proposal_id,
                "status": status,
                "reason": reason,
                "proposal_type": proposal.proposal_type,
                "source": proposal.source,
                "task_id": proposal.task_id,
            }
        )
        return proposal

    def proposal_summary(self) -> dict[str, Any]:
        return self.proposal_quarantine.summary()

    def proposals_by_status(self, status: str) -> list[ProposalRecord]:
        return self.proposal_quarantine.list(status=status)

    def accepted_structural_eval_proposals(self) -> list[ProposalRecord]:
        return self.proposal_quarantine.list(status="accepted_for_structural_eval")

    def review_pending_proposals(
        self,
        *,
        artifacts: list[dict] | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[ProposalRecord]:
        if self.proposal_reviewer is None:
            return []
        reviewed: list[ProposalRecord] = []
        pending = self.proposal_quarantine.list(status="under_review")
        enriched_context = dict(context or {})
        enriched_context["pending_proposals"] = pending
        for proposal in pending:
            decision = self.proposal_reviewer.review(
                self,
                proposal,
                artifacts=artifacts,
                context=enriched_context,
            )
            proposal.metadata.update(
                {
                    "support_roles": list(decision.support_roles),
                    "support_surfaces": list(decision.support_surfaces),
                    "support_surface_count": len(decision.support_surfaces),
                    "review_score": float(decision.score),
                    "matched_tokens": list(decision.matched_tokens),
                }
            )
            reviewed.append(
                self.review_proposal(
                    proposal.id,
                    status=decision.status,
                    reason=decision.reason,
                )
            )
        return reviewed

    def accepted_proposal_context(self) -> dict[str, Any]:
        accepted = self.accepted_structural_eval_proposals()
        candidate_labels = sorted(
            {
                str(proposal.payload.get("label"))
                for proposal in accepted
                if proposal.proposal_type == "semantic_label" and proposal.payload.get("label")
            }
        )
        hidden_variables = sorted(
            {
                str(proposal.payload.get("hidden_variable"))
                for proposal in accepted
                if proposal.proposal_type == "hidden_variable"
                and proposal.payload.get("hidden_variable")
            }
        )
        constraint_hints = sorted(
            {
                str(proposal.payload.get("constraint"))
                for proposal in accepted
                if proposal.proposal_type == "constraint" and proposal.payload.get("constraint")
            }
        )
        test_hints = sorted(
            {
                str(proposal.payload.get("test"))
                for proposal in accepted
                if proposal.proposal_type == "test" and proposal.payload.get("test")
            }
        )
        support_roles = sorted(
            {
                str(role)
                for proposal in accepted
                for role in proposal.metadata.get("support_roles", [])
            }
        )
        return {
            "candidate_labels": candidate_labels,
            "hidden_variables": hidden_variables,
            "constraint_hints": constraint_hints,
            "test_hints": test_hints,
            "support_roles": support_roles,
            "accepted_proposal_count": len(accepted),
        }

    def proposal_support_for_roles(self, roles: list[str]) -> float:
        if not roles:
            return 0.0
        target_roles = set(roles)
        score = 0.0
        for proposal in self.accepted_structural_eval_proposals():
            support_roles = set(str(role) for role in proposal.metadata.get("support_roles", []))
            overlap = support_roles & target_roles
            if not overlap:
                continue
            base = 1.0
            if proposal.proposal_type in {"semantic_label", "evidence_query"}:
                base = 0.5
            elif proposal.proposal_type == "test":
                base = 0.75
            score += base * (len(overlap) / max(len(target_roles), 1))
        return score

    def _run_proposal_stage(self, cycle_index: int) -> None:
        if self.proposal_session is None:
            return
        if not self.proposal_session["submitted"]:
            proposal_ids = self.transformer_propose(
                artifacts=self.proposal_session["artifacts"],
                context=self.proposal_session["context"],
                task_id=self.proposal_session["task_id"],
            )
            self.proposal_session["proposal_ids"] = proposal_ids
            self.proposal_session["submitted"] = True
        reviewed = self.review_pending_proposals(
            artifacts=self.proposal_session["artifacts"],
            context=self.proposal_session["context"],
        )
        self.telemetry.record_step(
            {
                "event_type": "proposal_stage",
                "cycle": cycle_index,
                "submitted_total": len(self.proposal_session.get("proposal_ids", [])),
                "reviewed_this_cycle": len(reviewed),
                "accepted_for_structural_eval": len(self.accepted_structural_eval_proposals()),
            }
        )

    def _sync_meta_symbol_state(self, meta_symbol: MetaSymbol) -> None:
        meta_symbol.updated_at = utc_now()
        if meta_symbol.id in self.graph.nodes:
            graph_meta_symbol = self.graph.get_node(meta_symbol.id)
            graph_meta_symbol.semantic_label = meta_symbol.semantic_label
            graph_meta_symbol.semantic_status = meta_symbol.semantic_status
            graph_meta_symbol.admission_status = meta_symbol.admission_status
            graph_meta_symbol.admission_metrics = dict(meta_symbol.admission_metrics)
            graph_meta_symbol.metadata = dict(meta_symbol.metadata)
            graph_meta_symbol.updated_at = meta_symbol.updated_at
        self.registry.sync_meta_symbol(meta_symbol)

    def _plateaued(self) -> bool:
        if len(self.psi_history) < self.config.plateau_window:
            return False
        window = self.psi_history[-self.config.plateau_window :]
        return max(window) - min(window) <= self.config.plateau_epsilon

    def _record_cycle_metrics(
        self,
        cycle_index: int,
        psi: float,
        q: float,
        lambda_max: float,
        kappa: float,
        proposal_support: float,
        hotspots: list,
        collapse_result,
    ) -> None:
        dpsi = 0.0 if len(self.psi_history) < 2 else self.psi_history[-1] - self.psi_history[-2]
        self.telemetry.record_step(
            {
                "event_type": "cycle",
                "cycle": cycle_index,
                "psi": psi,
                "dpsi_dt": dpsi,
                "q": q,
                "lambda_max": lambda_max,
                "kappa": kappa,
                "proposal_support": proposal_support,
                "hotspots": [
                    {
                        "cluster_id": hotspot.cluster_id,
                        "constraint_ids": hotspot.constraint_ids,
                        "symbol_ids": hotspot.symbol_ids,
                        "tension": hotspot.tension,
                        "persistence_mass": hotspot.persistence_mass,
                        "rank_score": hotspot.rank_score,
                    }
                    for hotspot in hotspots
                ],
                "collapse_method": collapse_result.method,
                "flipped_symbol_ids": collapse_result.flipped_symbol_ids,
                "graph_size": {
                    "nodes": len(self.graph.nodes),
                    "edges": len(self.graph.edges),
                    "active_constraints": len(self.graph.active_constraint_ids()),
                },
                "persistence_counters": dict(self.conflict_cache.persistence),
            }
        )

    def symbol_roles(
        self, symbol_ids: list[str], graph: PersistentGraph | None = None
    ) -> list[str]:
        return self.symbol_roles_with_field(symbol_ids, graph=graph, role_field="role")

    def symbol_roles_with_field(
        self,
        symbol_ids: list[str],
        graph: PersistentGraph | None = None,
        *,
        role_field: str = "role",
    ) -> list[str]:
        graph = graph or self.graph
        roles: list[str] = []
        for symbol_id in symbol_ids:
            if symbol_id not in graph.nodes:
                continue
            node = graph.get_node(symbol_id)
            roles.append(
                str(
                    node.metadata.get(
                        role_field,
                        node.metadata.get("role", getattr(node, "name", symbol_id).lower()),
                    )
                )
            )
        return roles

    def available_roles(
        self,
        graph: PersistentGraph | None = None,
        *,
        role_field: str = "role",
    ) -> list[str]:
        graph = graph or self.graph
        roles: list[str] = []
        for symbol in graph.iter_symbols():
            roles.append(
                str(
                    symbol.metadata.get(
                        role_field,
                        symbol.metadata.get("role", symbol.name.lower()),
                    )
                )
            )
        return roles

    def available_constraint_signatures(
        self,
        graph: PersistentGraph | None = None,
        *,
        role_field: str = "role",
    ) -> list[dict[str, Any]]:
        graph = graph or self.graph
        signatures: list[dict[str, Any]] = []
        for constraint in graph.iter_constraints(active_only=True):
            signatures.append(
                {
                    "constraint_id": constraint.id,
                    "kind": constraint.constraint_kind,
                    "roles": self.symbol_roles_with_field(
                        constraint.symbol_ids,
                        graph=graph,
                        role_field=role_field,
                    ),
                }
            )
        return signatures

    def find_reusable_candidates(
        self, graph: PersistentGraph | None = None
    ) -> list[dict[str, Any]]:
        graph = graph or self.graph
        return self.registry.find_reusable_candidates(
            available_roles=self.available_roles(graph=graph),
            constraint_signatures=self.available_constraint_signatures(graph=graph),
            available_canonical_roles=self.available_roles(
                graph=graph, role_field="canonical_role"
            ),
            canonical_constraint_signatures=self.available_constraint_signatures(
                graph=graph,
                role_field="canonical_role",
            ),
        )

    def apply_reusable_symbols(
        self,
        task_id: str,
        graph: PersistentGraph | None = None,
    ) -> list[dict[str, Any]]:
        graph = graph or self.graph
        applied: list[dict[str, Any]] = []
        for record in self.find_reusable_candidates(graph=graph):
            result = self._instantiate_reuse(record, graph=graph)
            if result["applied"]:
                self.telemetry.record_step(
                    {
                        "event_type": "reuse_application",
                        "task_id": task_id,
                        "source_meta_symbol_id": record["meta_symbol_id"],
                        "instantiated_meta_symbol_id": result["instantiated_meta_symbol_id"],
                        "matched_constraint_ids": result["matched_constraint_ids"],
                    }
                )
                applied.append(result)
        return applied

    def apply_registry_symbol(
        self,
        meta_symbol_id: str,
        task_id: str,
        graph: PersistentGraph | None = None,
    ) -> dict[str, Any]:
        graph = graph or self.graph
        record = self.registry.records[meta_symbol_id]
        result = self._instantiate_reuse(record, graph=graph)
        if result["applied"]:
            self.telemetry.record_step(
                {
                    "event_type": "reuse_application",
                    "task_id": task_id,
                    "source_meta_symbol_id": record["meta_symbol_id"],
                    "instantiated_meta_symbol_id": result["instantiated_meta_symbol_id"],
                    "matched_constraint_ids": result["matched_constraint_ids"],
                }
            )
        return result

    def _instantiate_reuse(
        self,
        record: dict[str, Any],
        graph: PersistentGraph | None = None,
    ) -> dict[str, Any]:
        graph = graph or self.graph
        signature = record.get("reuse_signature", {})
        reuse_match = record.get("reuse_match", {})
        role_field = str(reuse_match.get("role_field", "role"))
        parent_roles = reuse_match.get("parent_roles", signature.get("parent_roles", []))
        blanket_roles = reuse_match.get("blanket_roles", signature.get("blanket_roles", []))
        retired_constraint_signatures = reuse_match.get(
            "retired_constraint_signatures",
            signature.get("retired_constraint_signatures", []),
        )
        role_to_symbol_ids: dict[str, list[str]] = {}
        for symbol in graph.iter_symbols():
            role = str(
                symbol.metadata.get(
                    role_field,
                    symbol.metadata.get("role", symbol.name.lower()),
                )
            )
            role_to_symbol_ids.setdefault(role, []).append(symbol.id)

        required_roles = Counter(parent_roles) + Counter(blanket_roles)
        if any(
            len(role_to_symbol_ids.get(role, [])) < count for role, count in required_roles.items()
        ):
            return {"applied": False, "reason": "missing_roles"}

        parent_symbol_ids: list[str] = []
        used_ids: set[str] = set()
        for role in parent_roles:
            for candidate_id in role_to_symbol_ids.get(role, []):
                if candidate_id not in used_ids:
                    parent_symbol_ids.append(candidate_id)
                    used_ids.add(candidate_id)
                    break

        blanket_input_symbol_ids: list[str] = []
        for role in blanket_roles:
            for candidate_id in role_to_symbol_ids.get(role, []):
                if candidate_id not in used_ids:
                    blanket_input_symbol_ids.append(candidate_id)
                    used_ids.add(candidate_id)
                    break

        blanket_symbol_ids = list(blanket_input_symbol_ids)
        for role in sorted(set(blanket_roles)):
            for candidate_id in role_to_symbol_ids.get(role, []):
                if candidate_id not in blanket_symbol_ids and candidate_id not in parent_symbol_ids:
                    blanket_symbol_ids.append(candidate_id)

        matched_constraint_ids: list[str] = []
        for available_signature in self.available_constraint_signatures(
            graph=graph,
            role_field=role_field,
        ):
            for retired_signature in retired_constraint_signatures:
                if available_signature["kind"] == retired_signature.get("kind") and Counter(
                    available_signature["roles"]
                ) == Counter(retired_signature.get("roles", [])):
                    matched_constraint_ids.append(available_signature["constraint_id"])

        if retired_constraint_signatures and not matched_constraint_ids:
            return {"applied": False, "reason": "missing_matching_constraints"}

        interface_definition = self._remap_interface_definition(
            record,
            blanket_input_symbol_ids=blanket_input_symbol_ids,
            blanket_symbol_ids=blanket_symbol_ids,
            mapping_class=str(reuse_match.get("mapping_class", "exact")),
        )
        meta_symbol = MetaSymbol(
            id=graph.next_id("meta"),
            structural_name=record["structural_name"],
            semantic_label=record.get("semantic_label"),
            semantic_status=record.get("semantic_status", "deferred"),
            interface_kind=record.get("interface_kind", "exact"),
            interface_inputs=list(blanket_symbol_ids),
            interface_definition=interface_definition,
            parent_cluster_symbol_ids=list(parent_symbol_ids),
            markov_blanket_symbol_ids=list(blanket_symbol_ids),
            admission_status="accepted",
            metadata={
                "reused_from_meta_symbol_id": record["meta_symbol_id"],
                "reuse_signature": signature,
                "reuse_match": reuse_match,
            },
        )
        graph.add_node(meta_symbol)
        for symbol_id in parent_symbol_ids:
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=meta_symbol.id,
                    dst_id=symbol_id,
                    edge_kind="abstracts",
                )
            )

        for constraint_id in matched_constraint_ids:
            if constraint_id in graph.nodes:
                constraint = graph.get_node(constraint_id)
                constraint.active = False
                constraint.metadata["reused_by"] = meta_symbol.id

        return {
            "applied": True,
            "instantiated_meta_symbol_id": meta_symbol.id,
            "matched_constraint_ids": matched_constraint_ids,
            "parent_symbol_ids": parent_symbol_ids,
            "blanket_symbol_ids": blanket_symbol_ids,
            "blanket_input_symbol_ids": blanket_input_symbol_ids,
            "source_meta_symbol_id": record["meta_symbol_id"],
            "mapping_class": reuse_match.get("mapping_class", "exact"),
            "mapping_confidence": reuse_match.get("mapping_confidence", 1.0),
        }

    def _remap_interface_definition(
        self,
        record: dict[str, Any],
        *,
        blanket_input_symbol_ids: list[str],
        blanket_symbol_ids: list[str],
        mapping_class: str,
    ) -> dict[str, Any]:
        interface_definition = dict(record.get("interface_definition", {}))
        truth_table = interface_definition.get("truth_table")
        source_inputs = list(record.get("markov_blanket_symbol_ids", []))
        input_mapping = {
            source_input: target_input
            for source_input, target_input in zip(source_inputs, blanket_input_symbol_ids)
        }
        if isinstance(truth_table, dict) and input_mapping:
            remapped_truth_table: dict[str, bool] = {}
            for assignment_key, value in truth_table.items():
                terms: list[str] = []
                for assignment in str(assignment_key).split(","):
                    if "=" not in assignment:
                        continue
                    source_id, bit = assignment.split("=", 1)
                    target_id = input_mapping.get(source_id, source_id)
                    terms.append(f"{target_id}={bit}")
                remapped_truth_table[",".join(terms)] = bool(value)
            interface_definition["truth_table"] = remapped_truth_table
        notes = str(interface_definition.get("notes", "")).strip()
        interface_definition["notes"] = ",".join(
            part for part in [notes, f"remap:{mapping_class}"] if part
        )
        interface_definition["input_mapping"] = input_mapping
        interface_definition["expanded_blanket_symbol_ids"] = list(blanket_symbol_ids)
        return interface_definition

    def _build_reuse_signature(self, proposal, revision) -> dict[str, Any]:
        return {
            "parent_roles": self.symbol_roles(revision.cluster_symbol_ids),
            "blanket_roles": self.symbol_roles(proposal.interface_result.blanket_symbol_ids),
            "canonical_parent_roles": self.symbol_roles_with_field(
                revision.cluster_symbol_ids,
                role_field="canonical_role",
            ),
            "canonical_blanket_roles": self.symbol_roles_with_field(
                proposal.interface_result.blanket_symbol_ids,
                role_field="canonical_role",
            ),
            "retired_constraint_signatures": [
                {
                    "kind": self.graph.get_node(constraint_id).constraint_kind,
                    "roles": self.symbol_roles(self.graph.get_node(constraint_id).symbol_ids),
                }
                for constraint_id in revision.retired_constraint_ids
                if constraint_id in self.graph.nodes
            ],
            "canonical_retired_constraint_signatures": [
                {
                    "kind": self.graph.get_node(constraint_id).constraint_kind,
                    "roles": self.symbol_roles_with_field(
                        self.graph.get_node(constraint_id).symbol_ids,
                        role_field="canonical_role",
                    ),
                }
                for constraint_id in revision.retired_constraint_ids
                if constraint_id in self.graph.nodes
            ],
        }

    def _integrate_verification_feedback(
        self,
        meta_symbol_id: str,
        verification_result: VerificationResult,
    ) -> None:
        self.telemetry.record_step(
            {
                "event_type": "verification_feedback",
                "meta_symbol_id": meta_symbol_id,
                "verifier_name": verification_result.verifier_name,
                "status": verification_result.status,
                "passed": verification_result.passed,
                "failed": verification_result.failed,
                "cost": verification_result.cost,
            }
        )
        artifact = VerifierArtifact(
            id=self.graph.next_id("verifier"),
            verifier_name=verification_result.verifier_name,
            artifact_kind="verification_result",
            status=verification_result.status,
            cost=verification_result.cost,
            counterexample_ref=None if verification_result.counterexample is None else "inline",
            metadata={"details": verification_result.details},
        )
        self.graph.add_node(artifact)
        self.graph.add_edge(
            Edge(
                id=self.graph.next_id("edge"),
                src_id=artifact.id,
                dst_id=meta_symbol_id,
                edge_kind="supports" if verification_result.passed else "contradicts",
            )
        )
        if verification_result.counterexample is not None:
            evidence = Evidence(
                id=self.graph.next_id("evidence"),
                kind="counterexample",
                content_ref=str(verification_result.counterexample),
                source=verification_result.verifier_name,
                metadata={"counterexample": verification_result.counterexample},
            )
            self.graph.add_node(evidence)
            self.graph.add_edge(
                Edge(
                    id=self.graph.next_id("edge"),
                    src_id=evidence.id,
                    dst_id=meta_symbol_id,
                    edge_kind="contradicts",
                )
            )

    def _default_candidate_evaluation(
        self,
        proposal,
        revision,
        psi_before: float,
        psi_after: float,
    ) -> dict[str, Any]:
        reuse_signature = self._build_reuse_signature(proposal, revision)
        novelty_conflicts = self.registry.find_novelty_conflicts(
            parent_roles=reuse_signature["parent_roles"],
            blanket_roles=reuse_signature["blanket_roles"],
            interface_kind=proposal.meta_symbol.interface_kind,
            exclude_meta_symbol_id=proposal.meta_symbol.id,
        )
        complexity_penalty = float(
            len(revision.cluster_symbol_ids) + len(revision.retired_constraint_ids)
        )
        contradiction_gain = max(0.0, psi_before - psi_after)
        return {
            "novel": len(novelty_conflicts) == 0,
            "novelty_conflicts": novelty_conflicts,
            "verifier_passed": not self.config.require_verifier_for_admission,
            "reuse_passed": not self.config.require_reuse_for_admission,
            "heldout_contradiction_gain": contradiction_gain,
            "complexity_penalty": complexity_penalty,
            "rent_paid": contradiction_gain > 0.0,
        }

    def _admission_decision(
        self,
        meta_symbol_id: str,
        evaluation: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        accepted = True
        if self.config.require_novelty_for_admission and not bool(evaluation.get("novel", True)):
            accepted = False
            reasons.append("novelty_conflict")
        if self.config.require_verifier_for_admission and not bool(
            evaluation.get("verifier_passed", False)
        ):
            accepted = False
            reasons.append("verifier_failed")
        if self.config.require_reuse_for_admission and not bool(
            evaluation.get("reuse_passed", False)
        ):
            accepted = False
            reasons.append("reuse_failed")
        if (
            float(evaluation.get("heldout_contradiction_gain", 0.0))
            < self.config.min_heldout_contradiction_gain
        ):
            accepted = False
            reasons.append("insufficient_heldout_gain")
        if float(evaluation.get("complexity_penalty", 0.0)) > self.config.max_complexity_penalty:
            accepted = False
            reasons.append("symbolic_tax_too_high")
        if not bool(evaluation.get("rent_paid", True)):
            accepted = False
            reasons.append("symbol_did_not_pay_rent")
        return accepted, reasons

    def _handle_tsl_event(
        self,
        cycle_index: int,
        pathway: str,
        cluster,
        psi_before: float,
        psi_after: float,
    ) -> dict[str, Any] | None:
        blanket = self.tsl.compute_markov_blanket(
            self.graph, cluster.symbol_ids, cluster.constraint_ids
        )
        interface = self.tsl.synthesize_interface(self.graph, cluster, blanket)
        proposal = self.tsl.propose_meta_symbol(self.graph, cluster, interface, pathway=pathway)
        proposal_context = self.accepted_proposal_context()
        proposal.meta_symbol.metadata["structural_roles"] = self.symbol_roles(
            cluster.symbol_ids
        ) + self.symbol_roles(interface.blanket_symbol_ids)
        proposal.meta_symbol.metadata["proposal_support_roles"] = list(
            proposal_context["support_roles"]
        )
        proposal.meta_symbol.metadata["proposal_hidden_variables"] = list(
            proposal_context["hidden_variables"]
        )
        self.registry.record_candidate(proposal.meta_symbol)

        semantic_accepts = 0
        for label in self.semantic.propose_labels(
            proposal.meta_symbol,
            {
                "candidate_labels": [
                    *self.config.candidate_labels,
                    *proposal_context["candidate_labels"],
                ]
            },
        ):
            audit = self.semantic.audit(proposal.meta_symbol, label.label)
            self.registry.record_semantic_audit(proposal.meta_symbol.id, audit)
            if audit.accepted:
                semantic_accepts += 1
                if proposal.meta_symbol.semantic_label is None:
                    proposal.meta_symbol.semantic_label = label.label
                    proposal.meta_symbol.semantic_status = "grounded"
        self._sync_meta_symbol_state(proposal.meta_symbol)

        revision = self.tsl.apply_abstraction(self.graph, proposal)
        post_revision_psi = self.constraint_engine.compute_hamiltonian(
            self.graph, self.graph.assignment()
        )
        reuse_signature = self._build_reuse_signature(proposal, revision)
        self.registry.mark_reuse_signature(
            proposal.meta_symbol.id,
            parent_roles=reuse_signature["parent_roles"],
            blanket_roles=reuse_signature["blanket_roles"],
            retired_constraint_signatures=reuse_signature["retired_constraint_signatures"],
            canonical_parent_roles=reuse_signature["canonical_parent_roles"],
            canonical_blanket_roles=reuse_signature["canonical_blanket_roles"],
            canonical_retired_constraint_signatures=reuse_signature[
                "canonical_retired_constraint_signatures"
            ],
        )
        evaluation = self._default_candidate_evaluation(
            proposal, revision, psi_before, post_revision_psi
        )
        if self.candidate_evaluator is not None:
            custom = self.candidate_evaluator(
                self,
                {
                    "proposal": proposal,
                    "revision": revision,
                    "pathway": pathway,
                    "psi_before": psi_before,
                    "psi_after": post_revision_psi,
                },
            )
            evaluation.update(custom)

        verification_results = evaluation.pop("verification_results", [])
        for verification_result in verification_results:
            self.registry.record_verification(proposal.meta_symbol.id, verification_result)
            self._integrate_verification_feedback(proposal.meta_symbol.id, verification_result)
        for reuse_record in evaluation.pop("reuse_records", []):
            self.registry.record_reuse(
                proposal.meta_symbol.id,
                reuse_record["task_id"],
                reuse_record["outcome"],
            )
        self.telemetry.record_step(
            {
                "event_type": "candidate_evaluated",
                "cycle": cycle_index,
                "pathway": pathway,
                "meta_symbol_id": proposal.meta_symbol.id,
                "psi_before_revision": psi_before,
                "psi_after_revision": post_revision_psi,
                "verifier_passed": bool(evaluation.get("verifier_passed", False)),
                "reuse_passed": bool(evaluation.get("reuse_passed", False)),
                "heldout_contradiction_gain": float(
                    evaluation.get("heldout_contradiction_gain", 0.0)
                ),
                "complexity_penalty": float(evaluation.get("complexity_penalty", 0.0)),
                "rent_paid": bool(evaluation.get("rent_paid", False)),
                "proposal_support_roles": list(proposal_context["support_roles"]),
                "accepted_proposal_count": int(proposal_context["accepted_proposal_count"]),
                "evaluator": None
                if self.candidate_evaluator is None
                else self.candidate_evaluator.__class__.__name__,
            }
        )
        self.registry.update_admission_metrics(
            proposal.meta_symbol.id,
            {
                **evaluation,
                "semantic_accept_count": semantic_accepts,
                "pathway": pathway,
            },
        )
        proposal.meta_symbol.admission_metrics.update(
            {
                **evaluation,
                "semantic_accept_count": semantic_accepts,
                "pathway": pathway,
            }
        )
        self._sync_meta_symbol_state(proposal.meta_symbol)

        accepted, reasons = self._admission_decision(proposal.meta_symbol.id, evaluation)
        if accepted:
            retired_constraints = [
                self.graph.get_node(constraint_id)
                for constraint_id in revision.retired_constraint_ids
                if constraint_id in self.graph.nodes
            ]
            self.conflict_cache.reset_local(retired_constraints)
            self.tsl.local_reset(self.graph, revision)
            proposal.meta_symbol.admission_status = "accepted"
            self.registry.admit(
                proposal.meta_symbol.id, "accepted:" + ",".join(reasons or ["structural_relief"])
            )
            self._sync_meta_symbol_state(proposal.meta_symbol)
            self.telemetry.record_step(
                {
                    "event_type": "tsl_event",
                    "cycle": cycle_index,
                    "pathway": pathway,
                    "meta_symbol_id": revision.meta_symbol_id,
                    "retired_constraint_ids": revision.retired_constraint_ids,
                    "cluster_symbol_ids": revision.cluster_symbol_ids,
                    "admission_metrics": evaluation,
                }
            )
            if self.registry.should_retire(
                proposal.meta_symbol.id,
                max_failure_count=self.config.max_failure_count_before_retirement,
                min_reuse_successes=self.config.min_reuse_successes_before_retirement,
            ):
                proposal.meta_symbol.admission_status = "retired"
                self.registry.retire(proposal.meta_symbol.id, "post_admission_failure_threshold")
                self._sync_meta_symbol_state(proposal.meta_symbol)
            return {
                "proposal": proposal,
                "revision": revision,
                "evaluation": evaluation,
                "accepted": True,
            }

        self.tsl.rollback_abstraction(self.graph, revision)
        proposal.meta_symbol.admission_status = "rejected"
        self.registry.reject(proposal.meta_symbol.id, ",".join(reasons))
        self._sync_meta_symbol_state(proposal.meta_symbol)
        self.telemetry.record_step(
            {
                "event_type": "tsl_reject",
                "cycle": cycle_index,
                "pathway": pathway,
                "meta_symbol_id": proposal.meta_symbol.id,
                "reasons": reasons,
                "admission_metrics": evaluation,
            }
        )
        return {
            "proposal": proposal,
            "revision": None,
            "evaluation": evaluation,
            "accepted": False,
        }

    def run_cycle(self, cycle_index: int) -> dict:
        self._run_proposal_stage(cycle_index)
        assignment = self.graph.assignment()
        evaluations = self.constraint_engine.evaluate_all(self.graph, assignment)
        self.conflict_cache.record(self.graph, evaluations)
        psi_before = self.constraint_engine.compute_hamiltonian(self.graph, assignment)
        phi_before = self.constraint_engine.compute_local_potentials(self.graph, assignment)
        forcing = self.constraint_engine.compute_forcing_vector(self.graph, assignment)
        laplacian = self.spectral.build_laplacian(self.graph)
        lambda_max = self.spectral.estimate_lambda_max(laplacian)
        kappa = self.spectral.initialize_kappa(lambda_max, self.config.diffusion_safety_factor)
        diffusion = self.spectral.diffuse(phi_before, laplacian, forcing, kappa, lambda_max)
        q_before = self.spectral.quadratic_energy(phi_before, laplacian)
        collapse_result = self.collapse.run_cycle(
            self.graph, self.graph.assignment(), diffusion.phi_after
        )

        assignment_after = self.graph.assignment()
        evaluations_after = self.constraint_engine.evaluate_all(self.graph, assignment_after)
        self.conflict_cache.record(self.graph, evaluations_after)
        psi_after = self.constraint_engine.compute_hamiltonian(self.graph, assignment_after)
        phi_after = self.constraint_engine.compute_local_potentials(self.graph, assignment_after)
        q_after = self.spectral.quadratic_energy(phi_after, laplacian)
        hotspots = self.conflict_cache.rank_hotspots(self.graph)

        self.psi_history.append(psi_after)
        if hotspots:
            self.hotspot_history.append(hotspots[0].cluster_id)

        metrics = {
            "psi": psi_after,
            "plateaued": self._plateaued(),
            "top_hotspot_persistence": hotspots[0].persistence_mass if hotspots else 0.0,
            "hotspot_recurrence": self.hotspot_history.count(hotspots[0].cluster_id)
            if hotspots
            else 0,
            "proposal_support": self.proposal_support_for_roles(
                self.symbol_roles(hotspots[0].symbol_ids)
            )
            if hotspots
            else 0.0,
        }
        revision = None
        if hotspots and self.tsl.should_trigger_pathway_b(metrics):
            cluster = self.tsl.find_clusters(self.graph, hotspots, mode="FRUSTRATION")[0]
            event = self._handle_tsl_event(
                cycle_index=cycle_index,
                pathway="B",
                cluster=cluster,
                psi_before=psi_before,
                psi_after=psi_after,
            )
            if event and event["accepted"]:
                revision = event["revision"]
                psi_after = self.constraint_engine.compute_hamiltonian(
                    self.graph, self.graph.assignment()
                )
                phi_after = self.constraint_engine.compute_local_potentials(
                    self.graph, self.graph.assignment()
                )
                laplacian = self.spectral.build_laplacian(self.graph)
                q_after = self.spectral.quadratic_energy(phi_after, laplacian)
                hotspots = self.conflict_cache.rank_hotspots(self.graph)
        elif not hotspots and self.tsl.should_trigger_pathway_a(metrics):
            clusters = self.tsl.find_clusters(self.graph, hotspots, mode="COHERENCE")
            if clusters:
                event = self._handle_tsl_event(
                    cycle_index=cycle_index,
                    pathway="A",
                    cluster=clusters[0],
                    psi_before=psi_before,
                    psi_after=psi_after,
                )
                if event and event["accepted"]:
                    revision = event["revision"]
                    psi_after = self.constraint_engine.compute_hamiltonian(
                        self.graph, self.graph.assignment()
                    )
                    phi_after = self.constraint_engine.compute_local_potentials(
                        self.graph, self.graph.assignment()
                    )
                    laplacian = self.spectral.build_laplacian(self.graph)
                    q_after = self.spectral.quadratic_energy(phi_after, laplacian)

        self._record_cycle_metrics(
            cycle_index=cycle_index,
            psi=psi_after,
            q=q_after if psi_after != psi_before else q_before,
            lambda_max=lambda_max,
            kappa=kappa,
            proposal_support=metrics["proposal_support"],
            hotspots=hotspots,
            collapse_result=collapse_result,
        )
        return {
            "cycle": cycle_index,
            "psi_before": psi_before,
            "psi_after": psi_after,
            "q_before": q_before,
            "q_after": q_after,
            "proposal_support": metrics["proposal_support"],
            "hotspots": hotspots,
            "revision": revision,
        }

    def runtime_metrics(self) -> dict[str, Any]:
        cycles_to_first_accepted_symbol = None
        contradiction_before_acceptance = None
        false_candidate_count_before_acceptance = 0
        rollback_count_before_acceptance = 0
        verifier_calls_to_acceptance = 0
        proposal_stage_cycles = 0
        max_proposal_support = 0.0

        for event in self.telemetry.events:
            event_type = event.get("event_type")
            if event_type == "proposal_stage":
                proposal_stage_cycles += 1
            elif event_type == "cycle":
                max_proposal_support = max(
                    max_proposal_support,
                    float(event.get("proposal_support", 0.0)),
                )
            elif cycles_to_first_accepted_symbol is None and event_type == "tsl_reject":
                false_candidate_count_before_acceptance += 1
                rollback_count_before_acceptance += 1
            elif cycles_to_first_accepted_symbol is None and event_type == "verification_feedback":
                verifier_calls_to_acceptance += 1
            elif cycles_to_first_accepted_symbol is None and event_type == "candidate_evaluated":
                contradiction_before_acceptance = float(event.get("psi_before_revision", 0.0))
            elif cycles_to_first_accepted_symbol is None and event_type == "tsl_event":
                cycles_to_first_accepted_symbol = int(event.get("cycle", 0)) + 1

        return {
            "cycles_to_first_accepted_symbol": cycles_to_first_accepted_symbol,
            "verifier_calls_to_acceptance": verifier_calls_to_acceptance,
            "contradiction_before_acceptance": contradiction_before_acceptance,
            "false_candidate_count_before_acceptance": false_candidate_count_before_acceptance,
            "rollback_count_before_acceptance": rollback_count_before_acceptance,
            "proposal_stage_cycles": proposal_stage_cycles,
            "max_proposal_support": max_proposal_support,
            "accepted_proposal_count": len(self.accepted_structural_eval_proposals()),
        }

    def run_until_stable(self, max_cycles: int | None = None) -> dict:
        max_cycles = max_cycles or self.config.max_cycles
        last_result: dict = {}
        for cycle_index in range(max_cycles):
            last_result = self.run_cycle(cycle_index)
            if float(last_result.get("psi_after", 1.0)) <= 0.0:
                break
        return {
            "cycles_run": cycle_index + 1 if last_result else 0,
            "final_psi": last_result.get("psi_after"),
            "registry": self.registry.summary(),
            "telemetry_summary": self.telemetry.summary(),
            "runtime_metrics": self.runtime_metrics(),
        }
