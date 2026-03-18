"""External verifier bus."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .records import VerificationClaim, VerificationResult

VerifierFn = Callable[[VerificationClaim], VerificationResult]


class SubprocessVerifier:
    def __init__(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.command = list(command)
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    def __call__(self, claim: VerificationClaim) -> VerificationResult:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="densn_verifier_") as temp_dir:
            temp_path = Path(temp_dir)
            claim_path = temp_path / "claim.json"
            result_path = temp_path / "result.json"
            claim_path.write_text(
                json.dumps(
                    {
                        "kind": claim.kind,
                        "payload": claim.payload,
                        "context": claim.context,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            try:
                process = subprocess.run(
                    [*self.command, str(claim_path), str(result_path)],
                    cwd=self.cwd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    status="timeout",
                    passed=False,
                    failed=True,
                    counterexample=None,
                    cost=self.timeout_seconds,
                    artifact_ids=[],
                    verifier_name="subprocess",
                    details={"command": self.command},
                )

            elapsed = time.perf_counter() - started
            if not result_path.exists():
                return VerificationResult(
                    status="verifier_error",
                    passed=False,
                    failed=True,
                    counterexample=None,
                    cost=elapsed,
                    artifact_ids=[],
                    verifier_name="subprocess",
                    details={
                        "command": self.command,
                        "returncode": process.returncode,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                        "reason": "missing_result_file",
                    },
                )

            try:
                raw = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return VerificationResult(
                    status="verifier_error",
                    passed=False,
                    failed=True,
                    counterexample=None,
                    cost=elapsed,
                    artifact_ids=[],
                    verifier_name="subprocess",
                    details={
                        "command": self.command,
                        "returncode": process.returncode,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                        "reason": "invalid_result_json",
                        "exception": str(exc),
                    },
                )

            return VerificationResult(
                status=str(raw.get("status", "pass" if raw.get("passed") else "fail")),
                passed=bool(raw.get("passed", False)),
                failed=bool(raw.get("failed", not raw.get("passed", False))),
                counterexample=raw.get("counterexample"),
                cost=float(raw.get("cost", elapsed)),
                artifact_ids=list(raw.get("artifact_ids", [])),
                verifier_name=str(raw.get("verifier_name", "subprocess")),
                details={
                    **dict(raw.get("details", {})),
                    "command": self.command,
                    "returncode": process.returncode,
                },
            )


class RoleCountVerifier:
    """Generic invariant-shape verifier over canonical parent and blanket roles."""

    def __call__(self, claim: VerificationClaim) -> VerificationResult:
        started = time.perf_counter()
        payload = claim.payload
        parent_roles = Counter(
            str(role)
            for role in payload.get("canonical_parent_roles", payload.get("parent_roles", []))
        )
        blanket_roles = Counter(
            str(role)
            for role in payload.get("canonical_blanket_roles", payload.get("blanket_roles", []))
        )
        expected_parent = Counter(
            {
                str(role): int(count)
                for role, count in dict(payload.get("required_parent_role_counts", {})).items()
            }
        )
        expected_blanket = Counter(
            {
                str(role): int(count)
                for role, count in dict(payload.get("required_blanket_role_counts", {})).items()
            }
        )
        missing_parent = {
            role: count - parent_roles[role]
            for role, count in expected_parent.items()
            if parent_roles[role] < count
        }
        missing_blanket = {
            role: count - blanket_roles[role]
            for role, count in expected_blanket.items()
            if blanket_roles[role] < count
        }
        passed = not missing_parent and not missing_blanket
        return VerificationResult(
            status="pass" if passed else "fail",
            passed=passed,
            failed=not passed,
            counterexample=None
            if passed
            else {
                "reason": "missing_required_canonical_roles",
                "missing_parent": missing_parent,
                "missing_blanket": missing_blanket,
            },
            cost=time.perf_counter() - started,
            artifact_ids=[],
            verifier_name="role_count_verifier",
            details={
                "parent_roles": dict(parent_roles),
                "blanket_roles": dict(blanket_roles),
                "expected_parent": dict(expected_parent),
                "expected_blanket": dict(expected_blanket),
            },
        )


class TraceContractVerifier:
    """Generic trace/property checker driven by a claim-provided contract."""

    def __call__(self, claim: VerificationClaim) -> VerificationResult:
        started = time.perf_counter()
        payload = claim.payload
        manifest_path = payload.get("manifest_path")
        contract = dict(payload.get("trace_contract", {}))
        if not manifest_path or not contract:
            return VerificationResult(
                status="missing_contract",
                passed=False,
                failed=True,
                counterexample={"reason": "missing_manifest_or_trace_contract"},
                cost=time.perf_counter() - started,
                artifact_ids=[],
                verifier_name="trace_contract_verifier",
                details={},
            )
        manifest = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8"))
        contract_type = str(contract.get("type", ""))
        try:
            if contract_type == "window_guard":
                self._verify_window_guard_manifest(manifest, contract)
            elif contract_type == "gated_commit":
                self._verify_gated_commit_manifest(manifest, contract)
            else:
                raise ValueError(f"unsupported_trace_contract:{contract_type}")
        except ValueError as exc:
            return VerificationResult(
                status="fail",
                passed=False,
                failed=True,
                counterexample={"reason": str(exc)},
                cost=time.perf_counter() - started,
                artifact_ids=[],
                verifier_name="trace_contract_verifier",
                details={"manifest_path": str(Path(str(manifest_path)).resolve())},
            )
        return VerificationResult(
            status="pass",
            passed=True,
            failed=False,
            counterexample=None,
            cost=time.perf_counter() - started,
            artifact_ids=[],
            verifier_name="trace_contract_verifier",
            details={
                "manifest_path": str(Path(str(manifest_path)).resolve()),
                "trace_contract_type": contract_type,
            },
        )

    def _verify_window_guard_manifest(
        self, manifest: dict[str, Any], contract: dict[str, Any]
    ) -> None:
        open_token = str(contract["open_token"])
        close_token = str(contract["close_token"])
        action_token = str(contract["action_token"])
        for trace in manifest.get("execution_traces", []):
            if not self._window_guard_trace_valid(
                list(trace), open_token, close_token, action_token
            ):
                raise ValueError("valid_trace_rejected")
        for item in [
            *manifest.get("failing_tests", []),
            *manifest.get("counterexamples", []),
            *manifest.get("logs", []),
        ]:
            trace = list(item.get("trace", []))
            if trace and self._window_guard_trace_valid(
                trace, open_token, close_token, action_token
            ):
                raise ValueError("invalid_trace_accepted")

    def _window_guard_trace_valid(
        self,
        trace: list[str],
        open_token: str,
        close_token: str,
        action_token: str,
    ) -> bool:
        active = False
        for token in trace:
            if token == open_token:
                if active:
                    return False
                active = True
            elif token == close_token:
                if not active:
                    return False
                active = False
            elif token == action_token:
                if not active:
                    return False
            else:
                return False
        return not active

    def _verify_gated_commit_manifest(
        self, manifest: dict[str, Any], contract: dict[str, Any]
    ) -> None:
        prepare_token = str(contract["prepare_token"])
        commit_token = str(contract["commit_token"])
        clear_token = str(contract["clear_token"])
        counter_prefix = str(contract.get("counter_prefix", "ACK_"))
        required_counter_count = int(contract.get("required_counter_count", 2))
        stable_token = contract.get("stable_token")
        required_stable = bool(contract.get("required_stable", False))
        for trace in manifest.get("execution_traces", []):
            if not self._gated_commit_trace_valid(
                list(trace),
                prepare_token=prepare_token,
                commit_token=commit_token,
                clear_token=clear_token,
                counter_prefix=counter_prefix,
                required_counter_count=required_counter_count,
                stable_token=None if stable_token is None else str(stable_token),
                required_stable=required_stable,
            ):
                raise ValueError("valid_trace_rejected")
        for item in [
            *manifest.get("failing_tests", []),
            *manifest.get("counterexamples", []),
            *manifest.get("logs", []),
        ]:
            trace = list(item.get("trace", []))
            if trace and self._gated_commit_trace_valid(
                trace,
                prepare_token=prepare_token,
                commit_token=commit_token,
                clear_token=clear_token,
                counter_prefix=counter_prefix,
                required_counter_count=required_counter_count,
                stable_token=None if stable_token is None else str(stable_token),
                required_stable=required_stable,
            ):
                raise ValueError("invalid_trace_accepted")

    def _gated_commit_trace_valid(
        self,
        trace: list[str],
        *,
        prepare_token: str,
        commit_token: str,
        clear_token: str,
        counter_prefix: str,
        required_counter_count: int,
        stable_token: str | None,
        required_stable: bool,
    ) -> bool:
        active = False
        clear = False
        stable = False
        counter_count = 0
        for token in trace:
            if token == prepare_token:
                active = True
                clear = False
                stable = False
                counter_count = 0
            elif token == clear_token:
                if not active:
                    return False
                clear = True
            elif stable_token is not None and token == stable_token:
                if not active or not clear:
                    return False
                stable = True
            elif token.startswith(counter_prefix):
                if not active or not clear:
                    return False
                counter_count += 1
            elif token == commit_token:
                if (
                    not active
                    or not clear
                    or counter_count < required_counter_count
                    or (required_stable and not stable)
                ):
                    return False
                active = False
            else:
                return False
        return not active


class VerifierBus:
    def __init__(self) -> None:
        self._verifiers: dict[str, list[VerifierFn]] = {}
        self._descriptors: dict[str, list[dict[str, Any]]] = {}

    def register(
        self,
        claim_kind: str,
        verifier: VerifierFn,
        *,
        descriptor: dict[str, Any] | None = None,
        primary: bool = False,
    ) -> None:
        verifiers = self._verifiers.setdefault(claim_kind, [])
        descriptors = self._descriptors.setdefault(claim_kind, [])
        if primary:
            verifiers.insert(0, verifier)
            descriptors.insert(
                0,
                descriptor
                or {
                    "claim_kind": claim_kind,
                    "verifier_type": verifier.__class__.__name__,
                },
            )
            return
        verifiers.append(verifier)
        descriptors.append(
            descriptor
            or {
                "claim_kind": claim_kind,
                "verifier_type": verifier.__class__.__name__,
            }
        )

    def register_subprocess(
        self,
        claim_kind: str,
        command: list[str],
        cwd: str | None = None,
        timeout_seconds: float = 30.0,
        *,
        primary: bool = True,
    ) -> None:
        verifier = SubprocessVerifier(command=command, cwd=cwd, timeout_seconds=timeout_seconds)
        self.register(
            claim_kind,
            verifier,
            primary=primary,
            descriptor={
                "claim_kind": claim_kind,
                "verifier_type": "SubprocessVerifier",
                "command": list(command),
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            },
        )

    def register_role_count(self, claim_kind: str, *, primary: bool = False) -> None:
        self.register(
            claim_kind,
            RoleCountVerifier(),
            primary=primary,
            descriptor={
                "claim_kind": claim_kind,
                "verifier_type": "RoleCountVerifier",
            },
        )

    def register_trace_contract(self, claim_kind: str, *, primary: bool = False) -> None:
        self.register(
            claim_kind,
            TraceContractVerifier(),
            primary=primary,
            descriptor={
                "claim_kind": claim_kind,
                "verifier_type": "TraceContractVerifier",
            },
        )

    def verify(self, claim: VerificationClaim) -> VerificationResult:
        verifiers = self._verifiers.get(claim.kind, [])
        if not verifiers:
            return VerificationResult(
                status="missing_verifier",
                passed=False,
                failed=True,
                counterexample=None,
                cost=0.0,
                artifact_ids=[],
                verifier_name="none",
                details={"claim_kind": claim.kind},
            )
        return verifiers[0](claim)

    def verify_all(self, claim: VerificationClaim) -> list[VerificationResult]:
        verifiers = self._verifiers.get(claim.kind, [])
        if not verifiers:
            return [self.verify(claim)]
        return [verifier(claim) for verifier in verifiers]

    def agreement_summary(self, results: list[VerificationResult]) -> dict[str, Any]:
        if not results:
            return {
                "verifier_count": 0,
                "passed_count": 0,
                "failed_count": 0,
                "agreement_rate": 0.0,
                "all_agree": True,
                "disagreed": False,
            }
        passed_count = sum(1 for result in results if result.passed)
        failed_count = sum(1 for result in results if result.failed)
        all_agree = passed_count == len(results) or failed_count == len(results)
        majority = max(passed_count, failed_count)
        return {
            "verifier_count": len(results),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "agreement_rate": majority / max(len(results), 1),
            "all_agree": all_agree,
            "disagreed": not all_agree,
        }

    def describe(self) -> list[dict[str, Any]]:
        described: list[dict[str, Any]] = []
        for key in sorted(self._descriptors):
            described.extend(self._descriptors[key])
        return described
