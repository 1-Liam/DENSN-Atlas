"""Semantic bridge for provisional label audits."""

from __future__ import annotations

import re

from .records import LabelProposal, MetaSymbol, SemanticAuditResult


class SemanticBridge:
    def __init__(self, threshold: float = 0.1) -> None:
        self.threshold = threshold

    def propose_labels(
        self, meta_symbol: MetaSymbol, context: dict | None = None
    ) -> list[LabelProposal]:
        context = context or {}
        labels: list[LabelProposal] = []
        for label in context.get("candidate_labels", []):
            labels.append(LabelProposal(label=label, confidence=0.5, source="proposal_adapter"))
        structural_roles = [str(role) for role in meta_symbol.metadata.get("structural_roles", [])]
        unique_roles = sorted({role for role in structural_roles if role})
        if {"open", "close"}.issubset(set(unique_roles)) and "write" in unique_roles:
            labels.append(LabelProposal(label="WriteGuard", confidence=0.9, source="structural"))
        elif unique_roles:
            labels.append(
                LabelProposal(
                    label="_".join(unique_roles).title().replace("_", ""),
                    confidence=0.7,
                    source="structural",
                )
            )
        else:
            labels.append(
                LabelProposal(
                    label=meta_symbol.structural_name, confidence=0.5, source="structural"
                )
            )
        return labels

    def _tokens(self, text: str) -> set[str]:
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return {token for token in re.split(r"[^a-z0-9]+", normalized.lower()) if token}

    def measure_delta_psi(self, meta_symbol: MetaSymbol, label: str) -> float:
        compatible = {value.lower() for value in meta_symbol.metadata.get("compatible_labels", [])}
        structural_roles = {
            str(role).lower() for role in meta_symbol.metadata.get("structural_roles", [])
        }
        structural_terms = set(structural_roles)
        if {"open", "close"}.issubset(structural_roles):
            structural_terms.add("guard")
        label_tokens = self._tokens(label)
        if label.lower() == meta_symbol.structural_name.lower() or label.lower() in compatible:
            return 0.0
        if label_tokens and label_tokens.issubset(structural_terms | compatible):
            return self.threshold / 2.0
        overlap = len(label_tokens & structural_terms)
        if overlap > 0:
            return self.threshold * max(0.5, 1.0 - overlap / max(len(label_tokens), 1))
        return self.threshold * 2.0

    def audit(self, meta_symbol: MetaSymbol, label: str) -> SemanticAuditResult:
        delta_psi = self.measure_delta_psi(meta_symbol, label)
        accepted = delta_psi <= self.threshold
        return SemanticAuditResult(
            label=label,
            delta_psi=delta_psi,
            accepted=accepted,
            reason="bridge_pass" if accepted else "bridge_reject",
        )
