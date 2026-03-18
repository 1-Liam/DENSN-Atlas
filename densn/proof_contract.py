"""Shared proof-contract metadata for phase-5 evidence emission."""

from __future__ import annotations

from typing import Any

CORE_API_VERSION = "phase5_frozen_v1"
ALLOWED_CORE_MODES = {"mutable", "core_frozen"}


def proposal_adapter_summary(adapter: Any) -> dict[str, Any] | None:
    if adapter is None:
        return None
    describe = getattr(adapter, "describe", None)
    if callable(describe):
        return dict(describe())
    return {"adapter": adapter.__class__.__name__}


def transfer_metrics_summary(
    *,
    transfer_results: list[dict[str, Any]] | None = None,
    cross_family_cases: list[dict[str, Any]] | None = None,
    negative_transfer_case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if transfer_results is not None:
        positive = 0
        verifier_passes = 0
        total_gain = 0.0
        for result in transfer_results:
            verification = result.get("verification", {})
            summary = result.get("summary", {})
            if bool(verification.get("passed")):
                verifier_passes += 1
            if float(summary.get("final_psi") or 0.0) <= 0.0 and bool(verification.get("passed")):
                positive += 1
            contradiction_gain = result.get("contradiction_gain")
            if contradiction_gain is None:
                contradiction_gain = (
                    result.get("verification", {})
                    .get("details", {})
                    .get(
                        "contradiction_gain",
                        0.0,
                    )
                )
            total_gain += max(0.0, float(contradiction_gain or 0.0))
        return {
            "transfer_case_count": len(transfer_results),
            "positive_transfer_count": positive,
            "transfer_verifier_pass_count": verifier_passes,
            "transfer_contradiction_gain_sum": total_gain,
        }

    if cross_family_cases is not None or negative_transfer_case is not None:
        cases = list(cross_family_cases or [])
        blocked = sum(1 for case in cases if not bool(case.get("reuse_applied")))
        return {
            "cross_family_case_count": len(cases),
            "cross_family_block_count": blocked,
            "negative_transfer_blocked": bool(
                (negative_transfer_case or {}).get("negative_transfer_blocked", False)
            ),
        }

    return {}
