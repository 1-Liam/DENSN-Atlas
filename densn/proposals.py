"""Proposal quarantine for non-authoritative transformer outputs."""

from __future__ import annotations

from collections import Counter

from .records import ProposalRecord, utc_now


class ProposalQuarantine:
    def __init__(self) -> None:
        self.records: dict[str, ProposalRecord] = {}

    def submit(self, proposal: ProposalRecord) -> str:
        self.records[proposal.id] = proposal
        return proposal.id

    def submit_many(self, proposals: list[ProposalRecord]) -> list[str]:
        return [self.submit(proposal) for proposal in proposals]

    def get(self, proposal_id: str) -> ProposalRecord:
        return self.records[proposal_id]

    def list(self, status: str | None = None) -> list[ProposalRecord]:
        proposals = list(self.records.values())
        if status is not None:
            proposals = [proposal for proposal in proposals if proposal.status == status]
        proposals.sort(key=lambda proposal: proposal.created_at)
        return proposals

    def review(self, proposal_id: str, status: str, reason: str) -> ProposalRecord:
        proposal = self.records[proposal_id]
        proposal.status = status
        proposal.review_reason = reason
        proposal.reviewed_at = utc_now()
        return proposal

    def summary(self) -> dict[str, object]:
        status_counts = Counter(proposal.status for proposal in self.records.values())
        type_counts = Counter(proposal.proposal_type for proposal in self.records.values())
        return {
            "total": len(self.records),
            "status_counts": dict(status_counts),
            "type_counts": dict(type_counts),
            "pending_ids": [proposal.id for proposal in self.list(status="under_review")],
        }
