"""Core proposal review policies for quarantined transformer outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .artifacts import ArtifactBundle, load_artifact_bundle, normalize_tokens
from .records import ProposalRecord

if TYPE_CHECKING:
    from .system import DENSNSystem


@dataclass(frozen=True)
class ProposalDecision:
    status: str
    reason: str
    support_roles: list[str] = field(default_factory=list)
    support_surfaces: list[str] = field(default_factory=list)
    score: float = 0.0
    matched_tokens: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProposalReviewPolicy:
    name: str
    reject_shadowed_atoms: bool = False
    require_two_support_surfaces_for_atoms_and_labels: bool = False
    abstain_needs_more_evidence: bool = False
    abstain_score_threshold: float | None = None
    penalize_role_restatement: bool = False
    abstain_counterexample_only_tests: bool = False
    abstain_generic_semantic_alias_swaps: bool = False
    shadow_relationless_constraints: bool = False
    abstain_parent_only_tests: bool = False
    abstain_all_semantic_labels: bool = False


REVIEW_POLICY_CURRENT = ProposalReviewPolicy(name="current")
REVIEW_POLICY_ATOM_SHADOW_REJECT = ProposalReviewPolicy(
    name="atom_shadow_reject",
    reject_shadowed_atoms=True,
    penalize_role_restatement=True,
)
REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN = ProposalReviewPolicy(
    name="atom_shadow_reject_plus_abstain",
    reject_shadowed_atoms=True,
    require_two_support_surfaces_for_atoms_and_labels=True,
    abstain_needs_more_evidence=True,
    abstain_score_threshold=0.75,
    penalize_role_restatement=True,
    abstain_generic_semantic_alias_swaps=True,
)
REVIEW_POLICY_REAL_WORLD_STRICT = ProposalReviewPolicy(
    name="real_world_strict",
    reject_shadowed_atoms=True,
    require_two_support_surfaces_for_atoms_and_labels=True,
    abstain_needs_more_evidence=True,
    abstain_score_threshold=0.75,
    penalize_role_restatement=True,
    abstain_generic_semantic_alias_swaps=True,
    shadow_relationless_constraints=True,
    abstain_parent_only_tests=True,
    abstain_all_semantic_labels=True,
)

REVIEW_POLICIES: dict[str, ProposalReviewPolicy] = {
    REVIEW_POLICY_CURRENT.name: REVIEW_POLICY_CURRENT,
    REVIEW_POLICY_ATOM_SHADOW_REJECT.name: REVIEW_POLICY_ATOM_SHADOW_REJECT,
    REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN.name: REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN,
    REVIEW_POLICY_REAL_WORLD_STRICT.name: REVIEW_POLICY_REAL_WORLD_STRICT,
}


class ProposalReviewer:
    def review(
        self,
        system: "DENSNSystem",
        proposal: ProposalRecord,
        *,
        artifacts: list[dict] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProposalDecision:
        return ProposalDecision(status="rejected", reason="no_reviewer")


class ArtifactStructuralProposalReviewer(ProposalReviewer):
    """Review proposals against real artifact vocabulary and graph roles."""

    def __init__(
        self,
        *,
        policy: str | ProposalReviewPolicy = "atom_shadow_reject_plus_abstain",
    ) -> None:
        if isinstance(policy, ProposalReviewPolicy):
            self.policy = policy
        else:
            self.policy = REVIEW_POLICIES.get(policy, REVIEW_POLICY_ATOM_SHADOW_REJECT_PLUS_ABSTAIN)

    def review(
        self,
        system: "DENSNSystem",
        proposal: ProposalRecord,
        *,
        artifacts: list[dict] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProposalDecision:
        bundles = self._bundles(artifacts=artifacts, context=context)
        if not bundles:
            return ProposalDecision(status="rejected", reason="no_artifact_context")

        graph_roles = set(system.available_roles())
        bundle_roles = self._bundle_roles(bundles)
        proposal_tokens = self._proposal_tokens(proposal)
        matched_tokens = sorted(proposal_tokens & self._bundle_vocabulary(bundles))
        support_surfaces = self._support_surfaces(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            bundles=bundles,
        )
        shadowed_by_stronger_structure = self._shadowed_by_stronger_structure(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            bundles=bundles,
            context=context,
        )
        role_restatement = self._is_role_restatement(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            bundles=bundles,
        )
        semantic_label_missing_structural_anchor = self._semantic_label_missing_structural_anchor(
            proposal=proposal,
            bundles=bundles,
            context=context,
        )
        semantic_label_generic_alias_swap = self._semantic_label_generic_alias_swap(
            proposal=proposal,
            context=context,
        )
        counterexample_only_test = self._counterexample_only_test(
            proposal=proposal,
            bundles=bundles,
        )
        parent_only_test = self._parent_only_test(
            proposal=proposal,
            bundles=bundles,
        )
        support_roles = self._support_roles(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            graph_roles=graph_roles | bundle_roles,
            bundles=bundles,
        )
        score = self._score(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            matched_tokens=matched_tokens,
            support_roles=support_roles,
            support_surfaces=support_surfaces,
            bundles=bundles,
            shadowed_by_stronger_structure=shadowed_by_stronger_structure,
            role_restatement=role_restatement,
            semantic_label_missing_structural_anchor=semantic_label_missing_structural_anchor,
            semantic_label_generic_alias_swap=semantic_label_generic_alias_swap,
            counterexample_only_test=counterexample_only_test,
            parent_only_test=parent_only_test,
        )
        status, reason = self._decision(
            proposal=proposal,
            score=score,
            support_surfaces=support_surfaces,
            shadowed_by_stronger_structure=shadowed_by_stronger_structure,
            role_restatement=role_restatement,
            semantic_label_missing_structural_anchor=semantic_label_missing_structural_anchor,
            semantic_label_generic_alias_swap=semantic_label_generic_alias_swap,
            counterexample_only_test=counterexample_only_test,
            parent_only_test=parent_only_test,
        )
        return ProposalDecision(
            status=status,
            reason=reason,
            support_roles=support_roles,
            support_surfaces=support_surfaces,
            score=score,
            matched_tokens=matched_tokens,
        )

    def _proposal_tokens(self, proposal: ProposalRecord) -> set[str]:
        semantic_fields = []
        for key, value in proposal.payload.items():
            if key in {"artifact", "claim"}:
                continue
            semantic_fields.append(f"{key}={value}")
        return set(normalize_tokens(" ".join(semantic_fields)))

    def _core_payload_tokens(self, proposal: ProposalRecord) -> set[str]:
        payload_keys = {
            "atom": "atom",
            "constraint": "constraint",
            "hidden_variable": "hidden_variable",
            "semantic_label": "label",
            "test": "test",
            "evidence_query": "query",
        }
        payload_key = payload_keys.get(proposal.proposal_type, "")
        return set(normalize_tokens(str(proposal.payload.get(payload_key, ""))))

    def _bundles(
        self,
        *,
        artifacts: list[dict] | None,
        context: dict[str, Any] | None,
    ) -> list[ArtifactBundle]:
        manifest_paths: list[str] = []
        for artifact in artifacts or []:
            manifest_path = artifact.get("manifest_path")
            if manifest_path is not None:
                manifest_paths.append(str(manifest_path))
        for manifest_path in (context or {}).get("manifest_paths", []):
            manifest_paths.append(str(manifest_path))
        unique_paths = list(dict.fromkeys(manifest_paths))
        return [load_artifact_bundle(path) for path in unique_paths]

    def _bundle_roles(self, bundles: list[ArtifactBundle]) -> set[str]:
        roles: set[str] = set()
        for bundle in bundles:
            roles.update(bundle.role_aliases)
        return roles

    def _shadowed_by_stronger_structure(
        self,
        *,
        proposal: ProposalRecord,
        proposal_tokens: set[str],
        bundles: list[ArtifactBundle],
        context: dict[str, Any] | None,
    ) -> bool:
        if proposal.proposal_type not in {"atom", "constraint"}:
            return False
        semantic_tokens = self._core_payload_tokens(proposal)
        if not semantic_tokens:
            return False
        proposal_support_surfaces = self._support_surfaces(
            proposal=proposal,
            proposal_tokens=proposal_tokens,
            bundles=bundles,
        )
        for peer in (context or {}).get("pending_proposals", []):
            if peer.id == proposal.id:
                continue
            if proposal.proposal_type == "atom":
                allowed_peer_types = {"hidden_variable", "constraint"}
            else:
                allowed_peer_types = {"hidden_variable"}
            if peer.proposal_type not in allowed_peer_types:
                continue
            peer_tokens = self._core_payload_tokens(peer)
            peer_support_surfaces = self._support_surfaces(
                proposal=peer,
                proposal_tokens=self._proposal_tokens(peer),
                bundles=bundles,
            )
            has_relation_tokens = bool(
                {"requires", "implies", "after", "before", "until", "while", "if"} & semantic_tokens
            )
            sufficient_surface_support = len(peer_support_surfaces) >= len(
                proposal_support_surfaces
            )
            if (
                self.policy.shadow_relationless_constraints
                and proposal.proposal_type == "constraint"
                and not has_relation_tokens
            ):
                sufficient_surface_support = len(peer_support_surfaces) + 1 >= len(
                    proposal_support_surfaces
                )
            if (
                peer_tokens
                and semantic_tokens <= peer_tokens
                and sufficient_surface_support
                and (proposal.proposal_type == "atom" or not has_relation_tokens)
            ):
                return True
        return False

    def _bundle_vocabulary(self, bundles: list[ArtifactBundle]) -> set[str]:
        vocabulary: set[str] = set()
        for bundle in bundles:
            vocabulary.update(bundle.vocabulary)
            for aliases in bundle.role_aliases.values():
                vocabulary.update(aliases)
        return vocabulary

    def _support_surfaces(
        self,
        *,
        proposal: ProposalRecord,
        proposal_tokens: set[str],
        bundles: list[ArtifactBundle],
    ) -> list[str]:
        payload_text = json.dumps(proposal.payload, sort_keys=True)
        normalized_payload_tokens = set(normalize_tokens(payload_text))
        candidate_tokens = {
            token
            for token in (proposal_tokens | normalized_payload_tokens)
            if token
            not in {"artifact", "claim", "label", "hidden", "variable", "constraint", "atom"}
        }
        if not candidate_tokens:
            candidate_tokens = normalized_payload_tokens

        surfaces: set[str] = set()
        for bundle in bundles:
            manifest = bundle.manifest
            if candidate_tokens & set(normalize_tokens(str(manifest.get("description", "")))):
                surfaces.add("description")
            if candidate_tokens & set(
                normalize_tokens(str(manifest.get("natural_language_spec", "")))
            ):
                surfaces.add("natural_language_spec")
            if candidate_tokens & set(
                normalize_tokens(json.dumps(manifest.get("formal_spec", {})))
            ):
                surfaces.add("formal_spec")
            if candidate_tokens & set(
                normalize_tokens(json.dumps(manifest.get("execution_traces", [])))
            ):
                surfaces.add("execution_traces")
            failing_test_surface = set(
                normalize_tokens(json.dumps(manifest.get("failing_tests", [])))
            ) | {token for name in bundle.failing_test_names for token in normalize_tokens(name)}
            if candidate_tokens & failing_test_surface:
                surfaces.add("failing_tests")
            counterexample_surface = set(
                normalize_tokens(json.dumps(manifest.get("counterexamples", [])))
            ) | {token for name in bundle.counterexample_names for token in normalize_tokens(name)}
            if candidate_tokens & counterexample_surface:
                surfaces.add("counterexamples")
            if candidate_tokens & set(normalize_tokens(json.dumps(manifest.get("logs", [])))):
                surfaces.add("logs")
            source_surface = set(normalize_tokens(bundle.source_text)) | {
                token
                for variable in bundle.source_variables
                for token in normalize_tokens(variable)
            }
            if candidate_tokens & source_surface:
                surfaces.add("source_code")
        return sorted(surfaces)

    def _support_roles(
        self,
        *,
        proposal: ProposalRecord,
        proposal_tokens: set[str],
        graph_roles: set[str],
        bundles: list[ArtifactBundle],
    ) -> list[str]:
        support_roles = {
            role for role in proposal.metadata.get("support_roles", []) if role in graph_roles
        }
        for token in proposal_tokens:
            for bundle in bundles:
                for role in bundle.support_role_index.get(token, []):
                    if role in graph_roles:
                        support_roles.add(role)
        return sorted(support_roles)

    def _is_role_restatement(
        self,
        *,
        proposal: ProposalRecord,
        proposal_tokens: set[str],
        bundles: list[ArtifactBundle],
    ) -> bool:
        if proposal.proposal_type not in {"atom", "semantic_label"}:
            return False
        semantic_tokens = {token for token in proposal_tokens if token not in {"atom", "label"}}
        if not semantic_tokens:
            return False
        role_vocabulary: set[str] = set()
        for bundle in bundles:
            role_vocabulary.update(bundle.role_aliases)
            for aliases in bundle.role_aliases.values():
                role_vocabulary.update(aliases)
        interface_tokens = {"state", "active", "ready", "live", "guard", "invariant"}
        return semantic_tokens <= role_vocabulary and not (semantic_tokens & interface_tokens)

    def _semantic_label_missing_structural_anchor(
        self,
        *,
        proposal: ProposalRecord,
        bundles: list[ArtifactBundle],
        context: dict[str, Any] | None,
    ) -> bool:
        if proposal.proposal_type != "semantic_label":
            return False
        label_tokens = self._core_payload_tokens(proposal)
        if not label_tokens:
            return False
        qualifier_tokens = {"active", "ready", "live", "guard", "state", "invariant"}
        for peer in (context or {}).get("pending_proposals", []):
            if peer.id == proposal.id or peer.proposal_type not in {
                "hidden_variable",
                "constraint",
            }:
                continue
            peer_tokens = self._core_payload_tokens(peer)
            peer_qualifiers = peer_tokens & qualifier_tokens
            if peer_qualifiers:
                if label_tokens & peer_qualifiers:
                    return False
                continue
            if label_tokens & peer_tokens:
                return False
        return True

    def _semantic_label_generic_alias_swap(
        self,
        *,
        proposal: ProposalRecord,
        context: dict[str, Any] | None,
    ) -> bool:
        if proposal.proposal_type != "semantic_label":
            return False
        label_tokens = self._core_payload_tokens(proposal)
        if not label_tokens:
            return False
        generic_tokens = {"state", "active", "ready", "live", "guard", "invariant", "window"}
        for peer in (context or {}).get("pending_proposals", []):
            if peer.id == proposal.id or peer.proposal_type not in {
                "hidden_variable",
                "constraint",
            }:
                continue
            peer_tokens = self._core_payload_tokens(peer)
            shared_tokens = label_tokens & peer_tokens
            differing_tokens = label_tokens ^ peer_tokens
            if (
                shared_tokens
                and shared_tokens <= generic_tokens
                and differing_tokens
                and differing_tokens <= generic_tokens
            ):
                return True
        return False

    def _counterexample_only_test(
        self,
        *,
        proposal: ProposalRecord,
        bundles: list[ArtifactBundle],
    ) -> bool:
        if proposal.proposal_type != "test":
            return False
        artifact_hint = str(proposal.payload.get("artifact", "")).lower()
        if "counterexample" not in artifact_hint:
            return False
        test_name = str(proposal.payload.get("test", ""))
        failing_test_names = {name for bundle in bundles for name in bundle.failing_test_names}
        if not failing_test_names:
            return False
        return test_name not in failing_test_names

    def _parent_only_test(
        self,
        *,
        proposal: ProposalRecord,
        bundles: list[ArtifactBundle],
    ) -> bool:
        if proposal.proposal_type != "test":
            return False
        core_tokens = self._core_payload_tokens(proposal)
        if not core_tokens:
            return False
        blanketish = {"write", "ack", "clear", "stable"}
        parentish = {"open", "close", "commit", "pending", "prepare"}
        canonical_hits: set[str] = set()
        for bundle in bundles:
            canonical_roles = bundle.manifest.get("canonical_roles", {})
            for role_name, aliases in bundle.role_aliases.items():
                if core_tokens & set(aliases):
                    canonical_hits.add(str(canonical_roles.get(role_name, role_name)))
        if not canonical_hits:
            return False
        return bool(canonical_hits <= parentish and not (canonical_hits & blanketish))

    def _score(
        self,
        *,
        proposal: ProposalRecord,
        proposal_tokens: set[str],
        matched_tokens: list[str],
        support_roles: list[str],
        support_surfaces: list[str],
        bundles: list[ArtifactBundle],
        shadowed_by_stronger_structure: bool,
        role_restatement: bool,
        semantic_label_missing_structural_anchor: bool,
        semantic_label_generic_alias_swap: bool,
        counterexample_only_test: bool,
        parent_only_test: bool,
    ) -> float:
        score = 0.0
        if matched_tokens:
            score += 0.5
        if support_roles:
            score += 0.5
        if support_surfaces:
            score += min(0.5, 0.25 * len(support_surfaces))

        manifest = bundles[0].manifest
        source_variables = {variable.lower() for variable in bundles[0].source_variables}
        if proposal.proposal_type == "atom":
            atom_tokens = set(normalize_tokens(str(proposal.payload.get("atom", ""))))
            role_vocabulary: set[str] = set()
            for bundle in bundles:
                role_vocabulary.update(bundle.role_aliases)
                for aliases in bundle.role_aliases.values():
                    role_vocabulary.update(aliases)
            if (
                (
                    "guard" in proposal_tokens
                    and ("state" in proposal_tokens or "active" in proposal_tokens)
                )
                or (
                    "commit" in proposal_tokens
                    and ("ready" in proposal_tokens or "state" in proposal_tokens)
                )
                or ("credit" in proposal_tokens and "live" in proposal_tokens)
            ):
                score += 0.5
            if (
                atom_tokens
                and atom_tokens <= role_vocabulary
                and not ({"state", "active", "ready", "live"} & atom_tokens)
            ):
                score -= 1.0
            if {"requires", "implies", "after", "until", "holds", "xor"} & proposal_tokens:
                score -= 1.0
            if shadowed_by_stronger_structure:
                score -= 1.0
            if role_restatement:
                score -= 0.75
        elif proposal.proposal_type == "constraint":
            if (
                ("write" in proposal_tokens and "guard" in proposal_tokens)
                or (
                    "commit" in proposal_tokens
                    and (
                        "ack" in proposal_tokens
                        or "clear" in proposal_tokens
                        or "quorum" in proposal_tokens
                        or "ready" in proposal_tokens
                    )
                )
                or (
                    "charge" in proposal_tokens
                    and ("credit" in proposal_tokens or "balance" in proposal_tokens)
                )
            ):
                score += 0.5
            else:
                score -= 0.5
            if shadowed_by_stronger_structure:
                score -= 1.0
        elif proposal.proposal_type == "hidden_variable":
            formal_rules = set(
                normalize_tokens(json.dumps(manifest.get("formal_spec", {})).lower())
            )
            artifact_tokens = set(bundles[0].vocabulary)
            hidden_name = str(proposal.payload.get("hidden_variable", "")).lower()
            hidden_tokens = set(normalize_tokens(hidden_name))
            interface_tokens = {
                "state",
                "active",
                "ready",
                "live",
                "guard",
                "window",
                "term",
                "current",
                "committed",
                "quorum",
            }
            if (
                hidden_tokens
                and (hidden_tokens & (formal_rules | artifact_tokens))
                and hidden_name not in source_variables
            ):
                score += 0.75
            else:
                score -= 0.5
            weak_negative_tokens = {"expired", "expiry", "owner", "released", "stale"}
            if hidden_tokens & weak_negative_tokens and not (hidden_tokens & interface_tokens):
                score -= 1.5
            if hidden_name in source_variables and not (hidden_tokens & interface_tokens):
                score -= 0.75
        elif proposal.proposal_type == "semantic_label":
            label = str(proposal.payload.get("label", ""))
            label_tokens = set(normalize_tokens(label))
            qualifier_tokens = {"state", "active", "ready", "live", "guard", "invariant", "window"}
            if label_tokens == {"guard", "write"} or label_tokens == {"commit", "ready"}:
                score += 1.0
            elif {"credit", "live"} <= label_tokens:
                score += 0.75
            else:
                score -= 0.5
            if label_tokens and not (label_tokens & qualifier_tokens):
                score -= 0.75
            if role_restatement:
                score -= 0.75
            if semantic_label_missing_structural_anchor:
                score -= 0.75
            if semantic_label_generic_alias_swap:
                score -= 0.5
        elif proposal.proposal_type == "test":
            names = {
                *bundles[0].failing_test_names,
                *bundles[0].counterexample_names,
            }
            if str(proposal.payload.get("test", "")) in names:
                score += 1.0
            if counterexample_only_test:
                score -= 0.5
            if parent_only_test:
                score -= 1.0
        elif proposal.proposal_type == "evidence_query":
            query = set(normalize_tokens(str(proposal.payload.get("query", ""))))
            if query & set(bundles[0].vocabulary) and (
                {"guard", "invariant"} & query
                or {"commit", "ready"} & query
                or "quorum" in query
                or {"credit", "live"} & query
            ):
                score += 0.5

        return score

    def _decision(
        self,
        *,
        proposal: ProposalRecord,
        score: float,
        support_surfaces: list[str],
        shadowed_by_stronger_structure: bool,
        role_restatement: bool,
        semantic_label_missing_structural_anchor: bool,
        semantic_label_generic_alias_swap: bool,
        counterexample_only_test: bool,
        parent_only_test: bool,
    ) -> tuple[str, str]:
        if self.policy.abstain_all_semantic_labels and proposal.proposal_type == "semantic_label":
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "semantic_labels_deferred_by_policy"
            return "rejected", "semantic_labels_deferred_by_policy"

        if self.policy.reject_shadowed_atoms and shadowed_by_stronger_structure:
            return "rejected", "redundant_low_structure_shadow_of_hidden_variable"

        if (
            self.policy.abstain_generic_semantic_alias_swaps
            and proposal.proposal_type == "semantic_label"
            and semantic_label_generic_alias_swap
        ):
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "generic_semantic_alias_swap"
            return "rejected", "generic_semantic_alias_swap"

        if (
            self.policy.require_two_support_surfaces_for_atoms_and_labels
            and proposal.proposal_type in {"atom", "semantic_label"}
            and len(support_surfaces) < 2
        ):
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "needs_two_support_surfaces"
            return "rejected", "needs_two_support_surfaces"

        if (
            self.policy.penalize_role_restatement
            and proposal.proposal_type == "semantic_label"
            and semantic_label_missing_structural_anchor
        ):
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "semantic_label_needs_structural_anchor"
            return "rejected", "semantic_label_needs_structural_anchor"

        if (
            self.policy.abstain_counterexample_only_tests
            and proposal.proposal_type == "test"
            and counterexample_only_test
        ):
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "counterexample_test_needs_stronger_surface"
            return "rejected", "counterexample_test_needs_stronger_surface"

        if (
            self.policy.abstain_parent_only_tests
            and proposal.proposal_type == "test"
            and parent_only_test
        ):
            if self.policy.abstain_needs_more_evidence:
                return "abstain_needs_more_evidence", "test_targets_only_parent_roles"
            return "rejected", "test_targets_only_parent_roles"

        if self.policy.penalize_role_restatement and role_restatement and score < 1.0:
            return "rejected", "restates_existing_role_tokens"

        if score >= 1.0:
            return "accepted_for_structural_eval", "artifact_structural_support"

        if (
            self.policy.abstain_needs_more_evidence
            and self.policy.abstain_score_threshold is not None
            and score >= self.policy.abstain_score_threshold
        ):
            return "abstain_needs_more_evidence", "weak_support_needs_more_evidence"

        return "rejected", "insufficient_artifact_support"
