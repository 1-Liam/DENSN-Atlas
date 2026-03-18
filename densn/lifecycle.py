"""Core lifecycle evaluators for verifier-backed abstraction admission."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .records import MetaSymbol, VerificationClaim

if TYPE_CHECKING:
    from .graph import PersistentGraph
    from .system import DENSNConfig, DENSNSystem


@dataclass(frozen=True)
class HeldoutTaskSpec:
    task_id: str
    family: str
    split: str
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


GraphBuilder = Callable[[HeldoutTaskSpec, str], "PersistentGraph"]
ClaimBuilder = Callable[["DENSNSystem", MetaSymbol, HeldoutTaskSpec | None], VerificationClaim]
VerifierRegistrar = Callable[["DENSNSystem"], None]


class VerifierBackedReuseEvaluator:
    """Evaluate new abstractions against train and held-out verifier tasks."""

    def __init__(
        self,
        heldout_tasks: list[HeldoutTaskSpec],
        graph_builder: GraphBuilder,
        verifier_registrar: VerifierRegistrar,
        training_claim_builder: ClaimBuilder,
        heldout_claim_builder: ClaimBuilder,
        baseline_config: "DENSNConfig",
        reuse_config: "DENSNConfig",
    ) -> None:
        self.heldout_tasks = list(heldout_tasks)
        self.graph_builder = graph_builder
        self.verifier_registrar = verifier_registrar
        self.training_claim_builder = training_claim_builder
        self.heldout_claim_builder = heldout_claim_builder
        self.baseline_config = baseline_config
        self.reuse_config = reuse_config

    def __call__(self, system: "DENSNSystem", context: dict[str, Any]) -> dict[str, Any]:
        proposal = context["proposal"]
        meta_symbol = proposal.meta_symbol
        train_verification = system.verifier.verify(
            self.training_claim_builder(system, meta_symbol, None)
        )

        heldout_results: list[dict[str, Any]] = []
        reuse_records: list[dict[str, Any]] = []
        contradiction_gains: list[float] = []
        reuse_passed = True

        for task in self.heldout_tasks:
            baseline_graph = self.graph_builder(task, "baseline")
            baseline_system = system.__class__(
                baseline_graph,
                self.baseline_config,
                registry=system.registry,
            )
            self.verifier_registrar(baseline_system)
            baseline_summary = baseline_system.run_until_stable()

            reuse_graph = self.graph_builder(task, "reuse")
            reuse_system = system.__class__(
                reuse_graph, self.reuse_config, registry=system.registry
            )
            self.verifier_registrar(reuse_system)
            reuse_application = reuse_system.apply_registry_symbol(
                meta_symbol.id,
                task_id=task.task_id,
                graph=reuse_graph,
            )
            reuse_summary = reuse_system.run_until_stable()
            reuse_verification = reuse_system.verifier.verify(
                self.heldout_claim_builder(reuse_system, meta_symbol, task)
            )

            baseline_final_psi = float(baseline_summary.get("final_psi") or 0.0)
            reuse_final_psi = float(reuse_summary.get("final_psi") or 0.0)
            contradiction_gain = baseline_final_psi - reuse_final_psi
            reuse_success = (
                bool(reuse_application.get("applied"))
                and reuse_verification.passed
                and contradiction_gain > 0.0
            )

            contradiction_gains.append(contradiction_gain)
            reuse_passed = reuse_passed and reuse_success

            heldout_result = {
                "task_id": task.task_id,
                "family": task.family,
                "split": task.split,
                "baseline_final_psi": baseline_final_psi,
                "reuse_final_psi": reuse_final_psi,
                "contradiction_gain": contradiction_gain,
                "reuse_applied": reuse_application.get("applied", False),
                "verifier_passed": reuse_verification.passed,
            }
            heldout_results.append(heldout_result)
            reuse_records.append(
                {
                    "task_id": task.task_id,
                    "outcome": {
                        "reuse_passed": reuse_success,
                        "verifier_passed": reuse_verification.passed,
                        "reuse_applied": reuse_application.get("applied", False),
                        "heldout_final_psi": reuse_final_psi,
                        "contradiction_gain": contradiction_gain,
                    },
                }
            )

        average_gain = sum(contradiction_gains) / max(len(contradiction_gains), 1)
        return {
            "verification_results": [train_verification],
            "reuse_records": reuse_records,
            "verifier_passed": train_verification.passed,
            "reuse_passed": reuse_passed,
            "heldout_contradiction_gain": average_gain,
            "complexity_penalty": float(
                len(meta_symbol.parent_cluster_symbol_ids)
                + len(meta_symbol.markov_blanket_symbol_ids)
            ),
            "rent_paid": train_verification.passed
            and reuse_passed
            and all(gain > 0.0 for gain in contradiction_gains),
            "heldout_results": heldout_results,
        }
