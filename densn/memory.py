"""Ontology registry for accepted and rejected abstractions."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .records import MetaSymbol, SemanticAuditResult, VerificationResult


class OntologyRegistry:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    @classmethod
    def load(cls, path: str) -> "OntologyRegistry":
        registry = cls()
        registry.records = json.loads(Path(path).read_text(encoding="utf-8"))
        return registry

    def record_candidate(self, meta_symbol: MetaSymbol) -> None:
        existing = self.records.get(meta_symbol.id)
        record = {
            "meta_symbol_id": meta_symbol.id,
            "structural_name": meta_symbol.structural_name,
            "status": meta_symbol.admission_status,
            "semantic_label": meta_symbol.semantic_label,
            "semantic_status": meta_symbol.semantic_status,
            "interface_kind": meta_symbol.interface_kind,
            "interface_definition": dict(meta_symbol.interface_definition),
            "parent_cluster_symbol_ids": list(meta_symbol.parent_cluster_symbol_ids),
            "markov_blanket_symbol_ids": list(meta_symbol.markov_blanket_symbol_ids),
            "admission_metrics": dict(meta_symbol.admission_metrics),
            "audits": [],
            "verifications": [],
            "reuse": [],
            "rejection_history": [],
            "retirement_history": [],
            "lineage": {
                "created_at": meta_symbol.created_at,
                "parent_cluster_symbol_ids": list(meta_symbol.parent_cluster_symbol_ids),
                "markov_blanket_symbol_ids": list(meta_symbol.markov_blanket_symbol_ids),
            },
            "support_count": 0,
            "failure_count": 0,
            "verification_pass_count": 0,
            "verification_fail_count": 0,
            "reuse_pass_count": 0,
            "reuse_fail_count": 0,
            "times_reused": 0,
            "metadata": dict(meta_symbol.metadata),
        }
        if existing is not None:
            record["audits"] = list(existing.get("audits", []))
            record["verifications"] = list(existing.get("verifications", []))
            record["reuse"] = list(existing.get("reuse", []))
            record["rejection_history"] = list(existing.get("rejection_history", []))
            record["retirement_history"] = list(existing.get("retirement_history", []))
            record["support_count"] = int(existing.get("support_count", 0))
            record["failure_count"] = int(existing.get("failure_count", 0))
            record["verification_pass_count"] = int(existing.get("verification_pass_count", 0))
            record["verification_fail_count"] = int(existing.get("verification_fail_count", 0))
            record["reuse_pass_count"] = int(existing.get("reuse_pass_count", 0))
            record["reuse_fail_count"] = int(existing.get("reuse_fail_count", 0))
            record["times_reused"] = int(existing.get("times_reused", 0))
        self.records[meta_symbol.id] = record

    def record_semantic_audit(self, meta_symbol_id: str, audit_result: SemanticAuditResult) -> None:
        self.records[meta_symbol_id]["audits"].append(
            {
                "label": audit_result.label,
                "delta_psi": audit_result.delta_psi,
                "accepted": audit_result.accepted,
                "reason": audit_result.reason,
            }
        )

    def sync_meta_symbol(self, meta_symbol: MetaSymbol) -> None:
        if meta_symbol.id not in self.records:
            self.record_candidate(meta_symbol)
            return
        record = self.records[meta_symbol.id]
        record["structural_name"] = meta_symbol.structural_name
        record["status"] = meta_symbol.admission_status
        record["semantic_label"] = meta_symbol.semantic_label
        record["semantic_status"] = meta_symbol.semantic_status
        record["interface_kind"] = meta_symbol.interface_kind
        record["interface_definition"] = dict(meta_symbol.interface_definition)
        record["parent_cluster_symbol_ids"] = list(meta_symbol.parent_cluster_symbol_ids)
        record["markov_blanket_symbol_ids"] = list(meta_symbol.markov_blanket_symbol_ids)
        record["admission_metrics"] = dict(meta_symbol.admission_metrics)
        record["metadata"] = dict(meta_symbol.metadata)
        record["lineage"] = {
            "created_at": meta_symbol.created_at,
            "parent_cluster_symbol_ids": list(meta_symbol.parent_cluster_symbol_ids),
            "markov_blanket_symbol_ids": list(meta_symbol.markov_blanket_symbol_ids),
        }

    def record_verification(
        self, meta_symbol_id: str, verification_result: VerificationResult
    ) -> None:
        record = self.records[meta_symbol_id]
        record["verifications"].append(
            {
                "status": verification_result.status,
                "passed": verification_result.passed,
                "failed": verification_result.failed,
                "counterexample": verification_result.counterexample,
                "cost": verification_result.cost,
                "artifact_ids": verification_result.artifact_ids,
                "verifier_name": verification_result.verifier_name,
                "details": verification_result.details,
            }
        )
        if verification_result.passed:
            record["verification_pass_count"] += 1
            record["support_count"] += 1
        if verification_result.failed:
            record["verification_fail_count"] += 1
            record["failure_count"] += 1

    def record_reuse(self, meta_symbol_id: str, task_id: str, outcome: dict[str, Any]) -> None:
        record = self.records[meta_symbol_id]
        reuse_entry = {"task_id": task_id, **outcome}
        record["reuse"].append(reuse_entry)
        record["times_reused"] += 1
        if bool(outcome.get("verifier_passed")) or bool(outcome.get("reuse_passed")):
            record["reuse_pass_count"] += 1
            record["support_count"] += 1
        else:
            record["reuse_fail_count"] += 1
            record["failure_count"] += 1

    def admit(self, meta_symbol_id: str, reason: str) -> None:
        self.records[meta_symbol_id]["status"] = "accepted"
        self.records[meta_symbol_id]["admission_reason"] = reason

    def reject(self, meta_symbol_id: str, reason: str) -> None:
        self.records[meta_symbol_id]["status"] = "rejected"
        self.records[meta_symbol_id]["rejection_reason"] = reason
        self.records[meta_symbol_id]["rejection_history"].append(reason)
        self.records[meta_symbol_id]["failure_count"] += 1

    def retire(self, meta_symbol_id: str, reason: str) -> None:
        self.records[meta_symbol_id]["status"] = "retired"
        self.records[meta_symbol_id]["retirement_reason"] = reason
        self.records[meta_symbol_id]["retirement_history"].append(reason)

    def mark_reuse_signature(
        self,
        meta_symbol_id: str,
        parent_roles: list[str],
        blanket_roles: list[str],
        retired_constraint_signatures: list[dict[str, Any]],
        *,
        canonical_parent_roles: list[str] | None = None,
        canonical_blanket_roles: list[str] | None = None,
        canonical_retired_constraint_signatures: list[dict[str, Any]] | None = None,
    ) -> None:
        self.records[meta_symbol_id]["reuse_signature"] = {
            "parent_roles": list(parent_roles),
            "blanket_roles": list(blanket_roles),
            "retired_constraint_signatures": list(retired_constraint_signatures),
            "canonical_parent_roles": list(canonical_parent_roles or parent_roles),
            "canonical_blanket_roles": list(canonical_blanket_roles or blanket_roles),
            "canonical_retired_constraint_signatures": list(
                canonical_retired_constraint_signatures or retired_constraint_signatures
            ),
        }

    def update_admission_metrics(self, meta_symbol_id: str, metrics: dict[str, Any]) -> None:
        self.records[meta_symbol_id]["admission_metrics"].update(metrics)

    def find_novelty_conflicts(
        self,
        parent_roles: list[str],
        blanket_roles: list[str],
        interface_kind: str,
        exclude_meta_symbol_id: str | None = None,
    ) -> list[str]:
        conflicts: list[str] = []
        parent_counter = Counter(parent_roles)
        blanket_counter = Counter(blanket_roles)
        for meta_symbol_id, record in self.records.items():
            if exclude_meta_symbol_id is not None and meta_symbol_id == exclude_meta_symbol_id:
                continue
            if record.get("status") not in {"accepted", "candidate", "quarantined"}:
                continue
            signature = record.get("reuse_signature", {})
            if (
                Counter(signature.get("parent_roles", [])) == parent_counter
                and Counter(signature.get("blanket_roles", [])) == blanket_counter
                and record.get("interface_kind") == interface_kind
            ):
                conflicts.append(meta_symbol_id)
        return conflicts

    def find_reusable_candidates(
        self,
        available_roles: list[str],
        constraint_signatures: list[dict[str, Any]],
        *,
        available_canonical_roles: list[str] | None = None,
        canonical_constraint_signatures: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        role_counter = Counter(available_roles)
        canonical_counter = Counter(available_canonical_roles or available_roles)
        matches: list[dict[str, Any]] = []
        for meta_symbol_id, record in self.records.items():
            if record.get("status") != "accepted":
                continue
            signature = record.get("reuse_signature")
            if not signature:
                continue
            parent_roles = signature.get("parent_roles", [])
            blanket_roles = signature.get("blanket_roles", [])
            required_counter = Counter(parent_roles) + Counter(blanket_roles)
            retired_signatures = signature.get("retired_constraint_signatures", [])
            canonical_parent_roles = signature.get("canonical_parent_roles", parent_roles)
            canonical_blanket_roles = signature.get("canonical_blanket_roles", blanket_roles)
            canonical_required_counter = Counter(canonical_parent_roles) + Counter(
                canonical_blanket_roles
            )
            canonical_retired_signatures = signature.get(
                "canonical_retired_constraint_signatures",
                retired_signatures,
            )

            mapping_class = None
            mapping_confidence = 0.0
            role_field = "role"
            matched_parent_roles = parent_roles
            matched_blanket_roles = blanket_roles
            matched_retired_signatures = retired_signatures

            exact_role_match = not any(
                role_counter[role] < count for role, count in required_counter.items()
            )
            exact_constraint_match = (
                not retired_signatures
                or self._has_matching_constraint_signature(
                    retired_signatures,
                    constraint_signatures,
                )
            )
            if exact_role_match and exact_constraint_match:
                source_roles = Counter(parent_roles + blanket_roles)
                available_role_counter = Counter(available_roles)
                if available_role_counter == source_roles:
                    mapping_class = "exact"
                else:
                    mapping_class = "exact_blanket_expansion"
                mapping_confidence = 1.0
            else:
                canonical_role_match = not any(
                    canonical_counter[role] < count
                    for role, count in canonical_required_counter.items()
                )
                canonical_constraint_match = (
                    not canonical_retired_signatures
                    or self._has_matching_constraint_signature(
                        canonical_retired_signatures,
                        canonical_constraint_signatures or constraint_signatures,
                    )
                )
                if canonical_role_match and canonical_constraint_match:
                    mapping_class = "role_remap"
                    mapping_confidence = 0.85
                    role_field = "canonical_role"
                    matched_parent_roles = canonical_parent_roles
                    matched_blanket_roles = canonical_blanket_roles
                    matched_retired_signatures = canonical_retired_signatures
                else:
                    continue

            candidate = dict(record)
            candidate["reuse_match"] = {
                "mapping_class": mapping_class,
                "mapping_confidence": mapping_confidence,
                "role_field": role_field,
                "parent_roles": list(matched_parent_roles),
                "blanket_roles": list(matched_blanket_roles),
                "retired_constraint_signatures": list(matched_retired_signatures),
            }
            matches.append(candidate)
        matches.sort(
            key=lambda record: (
                int(record.get("reuse_pass_count", 0)),
                int(record.get("verification_pass_count", 0)),
                -int(record.get("failure_count", 0)),
            ),
            reverse=True,
        )
        return matches

    def should_retire(
        self,
        meta_symbol_id: str,
        max_failure_count: int = 3,
        min_reuse_successes: int = 1,
    ) -> bool:
        record = self.records[meta_symbol_id]
        if int(record.get("failure_count", 0)) >= max_failure_count:
            return True
        if (
            int(record.get("times_reused", 0)) >= min_reuse_successes
            and int(record.get("reuse_pass_count", 0)) == 0
        ):
            return True
        return False

    def _has_matching_constraint_signature(
        self,
        retired_signatures: list[dict[str, Any]],
        available_signatures: list[dict[str, Any]] | None,
    ) -> bool:
        if not available_signatures:
            return False
        for retired in retired_signatures:
            for available in available_signatures:
                if retired.get("kind") == available.get("kind") and Counter(
                    retired.get("roles", [])
                ) == Counter(available.get("roles", [])):
                    return True
        return False

    def summary(self) -> dict[str, int]:
        accepted = sum(1 for record in self.records.values() if record["status"] == "accepted")
        rejected = sum(1 for record in self.records.values() if record["status"] == "rejected")
        retired = sum(1 for record in self.records.values() if record["status"] == "retired")
        return {
            "total": len(self.records),
            "accepted": accepted,
            "rejected": rejected,
            "retired": retired,
        }

    def lifecycle_summary(self) -> dict[str, Any]:
        accepted_ids = [
            meta_symbol_id
            for meta_symbol_id, record in self.records.items()
            if record["status"] == "accepted"
        ]
        rejected_ids = [
            meta_symbol_id
            for meta_symbol_id, record in self.records.items()
            if record["status"] == "rejected"
        ]
        retired_ids = [
            meta_symbol_id
            for meta_symbol_id, record in self.records.items()
            if record["status"] == "retired"
        ]
        return {
            **self.summary(),
            "accepted_ids": accepted_ids,
            "rejected_ids": rejected_ids,
            "retired_ids": retired_ids,
            "total_reuse_passes": sum(
                int(record.get("reuse_pass_count", 0)) for record in self.records.values()
            ),
            "total_reuse_failures": sum(
                int(record.get("reuse_fail_count", 0)) for record in self.records.values()
            ),
            "total_verification_passes": sum(
                int(record.get("verification_pass_count", 0)) for record in self.records.values()
            ),
            "total_verification_failures": sum(
                int(record.get("verification_fail_count", 0)) for record in self.records.values()
            ),
        }

    def save(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.records, indent=2), encoding="utf-8")
