"""Typed records used across the DENSN research system."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def default_metadata() -> dict[str, Any]:
    return {}


def default_list() -> list[str]:
    return []


@dataclass
class AtomicSymbol:
    id: str
    name: str
    truth_value: bool = False
    locked: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    support_count: int = 0
    failure_count: int = 0
    provenance_ids: list[str] = field(default_factory=default_list)
    task_ids: list[str] = field(default_factory=default_list)
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="AtomicSymbol", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Constraint:
    id: str
    constraint_kind: str
    symbol_ids: list[str]
    weight: float = 1.0
    base_weight: float = 1.0
    max_weight: float = 16.0
    locked: bool = False
    active: bool = True
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    support_count: int = 0
    failure_count: int = 0
    persistence: int = 0
    provenance_ids: list[str] = field(default_factory=default_list)
    evaluator_key: str = ""
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="Constraint", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Observation:
    id: str
    symbol_id: str
    observed_value: bool
    locked: bool = True
    source: str = "unknown"
    created_at: str = field(default_factory=utc_now)
    provenance_ids: list[str] = field(default_factory=default_list)
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="Observation", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetaSymbol:
    id: str
    structural_name: str
    truth_value: bool = True
    locked: bool = False
    semantic_label: str | None = None
    semantic_status: str = "deferred"
    interface_kind: str = "structural_signature"
    interface_inputs: list[str] = field(default_factory=default_list)
    interface_definition: dict[str, Any] = field(default_factory=default_metadata)
    parent_cluster_symbol_ids: list[str] = field(default_factory=default_list)
    markov_blanket_symbol_ids: list[str] = field(default_factory=default_list)
    admission_status: str = "candidate"
    admission_metrics: dict[str, Any] = field(default_factory=default_metadata)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    provenance_ids: list[str] = field(default_factory=default_list)
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="MetaSymbol", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    id: str
    kind: str
    content_ref: str
    source: str
    created_at: str = field(default_factory=utc_now)
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="Evidence", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    id: str
    family: str
    split: str
    description: str
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="Task", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerifierArtifact:
    id: str
    verifier_name: str
    artifact_kind: str
    status: str
    cost: float
    counterexample_ref: str | None = None
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=default_metadata)
    node_type: str = field(default="VerifierArtifact", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Edge:
    id: str
    src_id: str
    dst_id: str
    edge_kind: str
    created_at: str = field(default_factory=utc_now)
    provenance_ids: list[str] = field(default_factory=default_list)
    metadata: dict[str, Any] = field(default_factory=default_metadata)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConstraintEvaluation:
    constraint_id: str
    violated: bool
    satisfied: bool
    weight: float
    details: dict[str, Any] = field(default_factory=default_metadata)


@dataclass
class HotspotScore:
    cluster_id: str
    constraint_ids: list[str]
    symbol_ids: list[str]
    tension: float
    persistence_mass: float
    rank_score: float


@dataclass
class MatrixBundle:
    row_labels: list[str]
    column_labels: list[str]
    matrix: list[list[float]]


@dataclass
class DiffusionStep:
    phi_before: dict[str, float]
    phi_after: dict[str, float]
    kappa: float
    lambda_max: float


@dataclass
class FlipCandidate:
    symbol_id: str
    phi: float
    delta_psi: float
    locked: bool


@dataclass
class CollapseCycle:
    flipped_symbol_ids: list[str]
    method: str
    escaped: bool
    psi_before: float
    psi_after: float


@dataclass
class ClusterCandidate:
    cluster_id: str
    symbol_ids: list[str]
    constraint_ids: list[str]
    score: float
    mode: str


@dataclass
class InterfaceSynthesisResult:
    mode: str
    blanket_symbol_ids: list[str]
    truth_table: dict[str, bool]
    satisfiable_cases: int
    total_cases: int
    notes: str


@dataclass
class MetaSymbolProposal:
    meta_symbol: MetaSymbol
    cluster: ClusterCandidate
    interface_result: InterfaceSynthesisResult


@dataclass
class TopologyRevision:
    meta_symbol_id: str
    retired_constraint_ids: list[str]
    cluster_symbol_ids: list[str]
    cluster_constraint_ids: list[str]


@dataclass
class LabelProposal:
    label: str
    confidence: float
    source: str


@dataclass
class SemanticAuditResult:
    label: str
    delta_psi: float
    accepted: bool
    reason: str


@dataclass
class VerificationClaim:
    kind: str
    payload: dict[str, Any]
    context: dict[str, Any] = field(default_factory=default_metadata)


@dataclass
class VerificationResult:
    status: str
    passed: bool
    failed: bool
    counterexample: dict[str, Any] | None
    cost: float
    artifact_ids: list[str]
    verifier_name: str
    details: dict[str, Any] = field(default_factory=default_metadata)


@dataclass
class BenchmarkTask:
    task_id: str
    family: str
    split: str
    inputs: dict[str, Any]
    expected_verifier_behavior: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=default_metadata)


@dataclass
class ProposalRecord:
    id: str
    proposal_type: str
    source: str
    payload: dict[str, Any]
    task_id: str | None = None
    status: str = "under_review"
    created_at: str = field(default_factory=utc_now)
    reviewed_at: str | None = None
    review_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=default_metadata)


NODE_TYPE_MAP = {
    "AtomicSymbol": AtomicSymbol,
    "Constraint": Constraint,
    "Observation": Observation,
    "MetaSymbol": MetaSymbol,
    "Evidence": Evidence,
    "Task": Task,
    "VerifierArtifact": VerifierArtifact,
}
