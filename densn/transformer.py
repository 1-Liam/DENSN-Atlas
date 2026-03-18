"""Swappable transformer-facing proposal adapters."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import uuid4

from .artifacts import ArtifactBundle, load_artifact_bundle, normalize_tokens
from .records import ProposalRecord

GROQ_MODEL_LIMITS: dict[str, dict[str, int | None]] = {
    "allam-2-7b": {"rpm": 30, "rpd": 7000, "tpm": 6000, "tpd": 500000},
    "groq/compound": {"rpm": 30, "rpd": 250, "tpm": 70000, "tpd": None},
    "groq/compound-mini": {"rpm": 30, "rpd": 250, "tpm": 70000, "tpd": None},
    "llama-3.1-8b-instant": {"rpm": 30, "rpd": 14400, "tpm": 6000, "tpd": 500000},
    "llama-3.3-70b-versatile": {"rpm": 30, "rpd": 1000, "tpm": 12000, "tpd": 100000},
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 30000,
        "tpd": 500000,
    },
    "meta-llama/llama-prompt-guard-2-22m": {
        "rpm": 30,
        "rpd": 14400,
        "tpm": 15000,
        "tpd": 500000,
    },
    "meta-llama/llama-prompt-guard-2-86m": {
        "rpm": 30,
        "rpd": 14400,
        "tpm": 15000,
        "tpd": 500000,
    },
    "moonshotai/kimi-k2-instruct": {"rpm": 60, "rpd": 1000, "tpm": 10000, "tpd": 300000},
    "moonshotai/kimi-k2-instruct-0905": {"rpm": 60, "rpd": 1000, "tpm": 10000, "tpd": 300000},
    "openai/gpt-oss-120b": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
}

GROQ_MODEL_RESPONSE_MODES: dict[str, list[str]] = {
    "groq/compound": ["json_object"],
    "groq/compound-mini": ["json_object"],
}

DEFAULT_GROQ_MODEL_CANDIDATES = [
    "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "groq/compound-mini",
]


class TransformerAdapter:
    def extract_atoms(
        self, artifacts: list[dict], task_id: str | None = None
    ) -> list[ProposalRecord]:
        return []

    def extract_constraints(
        self,
        artifacts: list[dict],
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return []

    def propose_hidden_variables(
        self,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return []

    def propose_labels(self, context: dict, task_id: str | None = None) -> list[ProposalRecord]:
        return []

    def generate_tests(
        self,
        claim: dict,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return []

    def retrieve_evidence(self, query: str, task_id: str | None = None) -> list[ProposalRecord]:
        return []


class ArtifactHeuristicTransformerAdapter(TransformerAdapter):
    """Heuristic proposal adapter that derives candidates from real artifact files."""

    def _proposal(
        self,
        proposal_type: str,
        payload: dict,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProposalRecord:
        return ProposalRecord(
            id=f"proposal_{uuid4().hex[:8]}",
            proposal_type=proposal_type,
            source="artifact_heuristic_adapter",
            payload=payload,
            task_id=task_id,
            metadata=dict(metadata or {}),
        )

    def _load_bundle(self, artifact: dict) -> ArtifactBundle | None:
        manifest_path = artifact.get("manifest_path")
        if manifest_path is None:
            return None
        return load_artifact_bundle(manifest_path)

    def extract_atoms(
        self, artifacts: list[dict], task_id: str | None = None
    ) -> list[ProposalRecord]:
        proposals: list[ProposalRecord] = []
        for artifact in artifacts:
            bundle = self._load_bundle(artifact)
            if bundle is None:
                continue
            formal_spec = json.dumps(bundle.manifest.get("formal_spec", {})).lower()
            if "guard" in formal_spec:
                proposals.append(
                    self._proposal(
                        proposal_type="atom",
                        payload={"atom": "guard_state", "artifact": bundle.manifest_path},
                        task_id=task_id,
                        metadata={"support_roles": ["open", "close", "write"]},
                    )
                )
            if "commit" in formal_spec and "ack" in formal_spec:
                proposals.append(
                    self._proposal(
                        proposal_type="atom",
                        payload={"atom": "commit_ready", "artifact": bundle.manifest_path},
                        task_id=task_id,
                        metadata={
                            "support_roles": ["prepare", "commit", "pending", "ack", "clear"]
                        },
                    )
                )
            for variable in bundle.source_variables[:1]:
                proposals.append(
                    self._proposal(
                        proposal_type="atom",
                        payload={
                            "atom": variable,
                            "artifact": bundle.source_path or bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["open"] if "begin" in variable.lower() else []},
                    )
                )
        return proposals

    def extract_constraints(
        self,
        artifacts: list[dict],
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        proposals: list[ProposalRecord] = []
        for artifact in artifacts:
            bundle = self._load_bundle(artifact)
            if bundle is None:
                continue
            rules = [
                str(rule).lower()
                for rule in bundle.manifest.get("formal_spec", {}).get("rules", [])
            ]
            if any("write" in rule and "guard_active" in rule for rule in rules):
                proposals.append(
                    self._proposal(
                        proposal_type="constraint",
                        payload={
                            "constraint": "write_requires_guard",
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["write", "open", "close"]},
                    )
                )
            if any("trace_end" in rule for rule in rules):
                proposals.append(
                    self._proposal(
                        proposal_type="constraint",
                        payload={
                            "constraint": "trace_end_requires_guard_closed",
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["close"]},
                    )
                )
            if any("commit" in rule and "ack" in rule for rule in rules):
                proposals.append(
                    self._proposal(
                        proposal_type="constraint",
                        payload={
                            "constraint": "commit_requires_commit_ready",
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["commit", "pending", "ack", "clear"]},
                    )
                )
        return proposals

    def propose_hidden_variables(
        self,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        proposals: list[ProposalRecord] = []
        for manifest_path in context.get("manifest_paths", []):
            bundle = load_artifact_bundle(manifest_path)
            if (
                "guard_active" in json.dumps(bundle.manifest.get("formal_spec", {})).lower()
                and "guard_active" not in bundle.source_text
            ):
                proposals.append(
                    self._proposal(
                        proposal_type="hidden_variable",
                        payload={
                            "hidden_variable": "guard_active",
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["open", "close", "write"]},
                    )
                )
            if "saw_begin" in bundle.source_text:
                proposals.append(
                    self._proposal(
                        proposal_type="hidden_variable",
                        payload={
                            "hidden_variable": "saw_begin",
                            "artifact": bundle.source_path or bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={"support_roles": ["open"]},
                    )
                )
            if (
                "commit_ready" in json.dumps(bundle.manifest, sort_keys=True).lower()
                and "commit_ready" not in bundle.source_text
            ):
                proposals.append(
                    self._proposal(
                        proposal_type="hidden_variable",
                        payload={
                            "hidden_variable": "commit_ready",
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={
                            "support_roles": ["prepare", "commit", "pending", "ack", "clear"]
                        },
                    )
                )
        return proposals

    def propose_labels(self, context: dict, task_id: str | None = None) -> list[ProposalRecord]:
        proposals: list[ProposalRecord] = []
        for manifest_path in context.get("manifest_paths", []):
            bundle = load_artifact_bundle(manifest_path)
            spec_text = str(bundle.manifest.get("natural_language_spec", "")).lower()
            if "guard" in spec_text:
                proposals.append(
                    self._proposal(
                        proposal_type="semantic_label",
                        payload={"label": "WriteGuard", "artifact": bundle.manifest_path},
                        task_id=task_id,
                        metadata={"support_roles": ["open", "close", "write"]},
                    )
                )
            if "commit" in spec_text and "acknowledgement" in spec_text:
                proposals.append(
                    self._proposal(
                        proposal_type="semantic_label",
                        payload={"label": "CommitReady", "artifact": bundle.manifest_path},
                        task_id=task_id,
                        metadata={
                            "support_roles": ["prepare", "commit", "pending", "ack", "clear"]
                        },
                    )
                )
            proposals.append(
                self._proposal(
                    proposal_type="semantic_label",
                    payload={"label": "SawBeginMemory", "artifact": bundle.manifest_path},
                    task_id=task_id,
                    metadata={"support_roles": ["open"]},
                )
            )
        return proposals

    def generate_tests(
        self,
        claim: dict,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        proposals: list[ProposalRecord] = []
        for manifest_path in context.get("manifest_paths", []):
            bundle = load_artifact_bundle(manifest_path)
            failing_tests = bundle.manifest.get("failing_tests", [])
            for test in failing_tests[:2]:
                proposals.append(
                    self._proposal(
                        proposal_type="test",
                        payload={
                            "test": test.get("name"),
                            "claim": claim,
                            "artifact": bundle.manifest_path,
                        },
                        task_id=task_id,
                        metadata={
                            "support_roles": [
                                role
                                for role in (
                                    "open",
                                    "close",
                                    "write",
                                    "prepare",
                                    "commit",
                                    "pending",
                                    "ack",
                                    "clear",
                                )
                                if role in bundle.role_aliases
                            ],
                        },
                    )
                )
        return proposals

    def retrieve_evidence(self, query: str, task_id: str | None = None) -> list[ProposalRecord]:
        if not query:
            return []
        return [
            self._proposal(
                proposal_type="evidence_query",
                payload={"query": query},
                task_id=task_id,
            )
        ]


class OpenAIChatTransformerAdapter(TransformerAdapter):
    """Live adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
        max_completion_tokens: int = 1200,
        response_format_mode: str = "json_object",
    ) -> None:
        self.model = model or os.getenv("DENSN_TRANSFORMER_MODEL") or "gpt-5-mini"
        self.api_key_env = api_key_env
        self.base_url = (
            base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1/chat/completions"
        )
        self.timeout_seconds = _env_float("DENSN_TRANSFORMER_TIMEOUT_SECONDS", timeout_seconds)
        self.temperature = temperature
        self.max_completion_tokens = _env_int(
            "DENSN_TRANSFORMER_MAX_COMPLETION_TOKENS",
            max_completion_tokens,
        )
        self.response_format_mode = response_format_mode
        self.source_name = "openai_chat_adapter"
        self._proposal_cache: dict[str, list[ProposalRecord]] = {}
        self.max_rules = _env_int("DENSN_TRANSFORMER_MAX_RULES", 6)
        self.max_failing_tests = _env_int("DENSN_TRANSFORMER_MAX_FAILING_TESTS", 2)
        self.max_counterexamples = _env_int("DENSN_TRANSFORMER_MAX_COUNTEREXAMPLES", 2)
        self.max_logs = _env_int("DENSN_TRANSFORMER_MAX_LOGS", 2)
        self.max_source_variables = _env_int("DENSN_TRANSFORMER_MAX_SOURCE_VARIABLES", 12)
        self.source_excerpt_chars = _env_int("DENSN_TRANSFORMER_SOURCE_TEXT_CHARS", 1600)
        self.max_backfill_requests = _env_int("DENSN_TRANSFORMER_MAX_BACKFILL_REQUESTS", 2)
        self.max_attempts = _env_int("DENSN_TRANSFORMER_MAX_ATTEMPTS", 3)
        self.max_retry_after_seconds = _env_float("DENSN_TRANSFORMER_MAX_RETRY_AFTER_SECONDS", 5.0)
        self.request_trace_path = os.getenv("DENSN_TRANSFORMER_REQUEST_TRACE_PATH")

    def is_configured(self) -> bool:
        return bool(os.getenv(self.api_key_env))

    def describe(self) -> dict[str, Any]:
        return {
            "adapter": self.__class__.__name__,
            "configured": self.is_configured(),
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }

    def extract_atoms(
        self, artifacts: list[dict], task_id: str | None = None
    ) -> list[ProposalRecord]:
        return self._filter_proposals(
            self._generate_all(artifacts=artifacts, task_id=task_id),
            {"atom"},
        )

    def extract_constraints(
        self,
        artifacts: list[dict],
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return self._filter_proposals(
            self._generate_all(artifacts=artifacts, task_id=task_id),
            {"constraint"},
        )

    def propose_hidden_variables(
        self,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return self._filter_proposals(
            self._generate_all(
                artifacts=self._artifacts_from_context(context),
                task_id=task_id,
            ),
            {"hidden_variable"},
        )

    def propose_labels(self, context: dict, task_id: str | None = None) -> list[ProposalRecord]:
        return self._filter_proposals(
            self._generate_all(
                artifacts=self._artifacts_from_context(context),
                task_id=task_id,
            ),
            {"semantic_label"},
        )

    def generate_tests(
        self,
        claim: dict,
        context: dict,
        task_id: str | None = None,
    ) -> list[ProposalRecord]:
        return self._filter_proposals(
            self._generate_all(
                artifacts=self._artifacts_from_context(context),
                task_id=task_id,
            ),
            {"test"},
        )

    def retrieve_evidence(self, query: str, task_id: str | None = None) -> list[ProposalRecord]:
        if not query:
            return []
        return [
            ProposalRecord(
                id=f"proposal_{uuid4().hex[:8]}",
                proposal_type="evidence_query",
                source=self.source_name,
                payload={"query": query},
                task_id=task_id,
                metadata={"support_roles": []},
            )
        ]

    def _generate(
        self,
        artifacts: list[dict],
        task_id: str | None,
        query: str,
        allowed_types: set[str] | None = None,
    ) -> list[ProposalRecord]:
        if not self.is_configured():
            raise RuntimeError(f"{self.__class__.__name__} requires {self.api_key_env} to be set.")
        bundles = [
            load_artifact_bundle(artifact["manifest_path"])
            for artifact in artifacts
            if "manifest_path" in artifact
        ]
        if not bundles:
            return []
        prompt = self._build_prompt(bundles=bundles, query=query)
        parsed = self.request_json_object(prompt)
        return self._records_from_payload(parsed, task_id=task_id, allowed_types=allowed_types)

    def request_json_object(self, prompt: str) -> dict[str, Any]:
        raw = self._request_json(prompt)
        return self._parse_response_json(raw)

    def _generate_all(
        self,
        *,
        artifacts: list[dict],
        task_id: str | None,
    ) -> list[ProposalRecord]:
        cache_key = self._cache_key(artifacts)
        if cache_key in self._proposal_cache:
            return list(self._proposal_cache[cache_key])
        proposals = self._generate(
            artifacts=artifacts,
            task_id=task_id,
            query=(
                "Return the strongest grounded proposals across all categories. "
                "At minimum, if the artifacts support them, return one hidden variable, "
                "one core constraint or invariant, up to two tests, and one semantic label."
            ),
            allowed_types=None,
        )
        if not proposals:
            proposals = self._generate(
                artifacts=artifacts,
                task_id=task_id,
                query=(
                    "Retry with extra strictness: return every supported category, and if a category "
                    "has no grounded candidate return an empty array explicitly."
                ),
                allowed_types=None,
            )
        proposals = self._backfill_missing_categories(
            artifacts=artifacts,
            task_id=task_id,
            proposals=proposals,
        )
        self._proposal_cache[cache_key] = list(proposals)
        return list(proposals)

    def _backfill_missing_categories(
        self,
        *,
        artifacts: list[dict],
        task_id: str | None,
        proposals: list[ProposalRecord],
    ) -> list[ProposalRecord]:
        merged = list(proposals)
        existing_types = {proposal.proposal_type for proposal in merged}
        backfill_requests = 0
        for proposal_type in ("hidden_variable", "constraint", "test", "semantic_label"):
            if backfill_requests >= self.max_backfill_requests:
                break
            if proposal_type in existing_types:
                continue
            targeted = self._generate(
                artifacts=artifacts,
                task_id=task_id,
                query=self._targeted_query(proposal_type),
                allowed_types={proposal_type},
            )
            backfill_requests += 1
            merged = self._merge_unique_proposals(merged, targeted)
            existing_types = {proposal.proposal_type for proposal in merged}
        if not any(
            proposal.proposal_type in {"hidden_variable", "constraint", "test"}
            for proposal in merged
        ):
            if backfill_requests >= self.max_backfill_requests:
                return merged
            targeted_atom = self._generate(
                artifacts=artifacts,
                task_id=task_id,
                query=self._targeted_query("atom"),
                allowed_types={"atom"},
            )
            merged = self._merge_unique_proposals(merged, targeted_atom)
        return merged

    def _targeted_query(self, proposal_type: str) -> str:
        instructions = {
            "atom": (
                "Return only an atom if the artifacts name a grounded missing state token. "
                "Do not return ordinary source variables or a synonym for a stronger hidden variable."
            ),
            "constraint": (
                "Return only the single strongest invariant or constraint that links the key surface actions "
                "to the missing latent condition from the formal artifacts."
            ),
            "hidden_variable": (
                "Return only the single strongest missing hidden variable or latent state from the formal "
                "specification that is absent from the implementation."
            ),
            "semantic_label": (
                "Return only the single strongest short reusable semantic label for the grounded missing "
                "state or invariant."
            ),
            "test": (
                "Return up to two concrete failing tests or counterexample names that most directly expose "
                "the missing hidden state or invariant."
            ),
        }
        return instructions.get(
            proposal_type,
            "Return only grounded proposals supported directly by the supplied artifacts.",
        )

    def _merge_unique_proposals(
        self,
        existing: list[ProposalRecord],
        extras: list[ProposalRecord],
    ) -> list[ProposalRecord]:
        merged = list(existing)
        index = {self._proposal_identity(proposal): proposal for proposal in merged}
        for proposal in extras:
            identity = self._proposal_identity(proposal)
            if identity not in index:
                merged.append(proposal)
                index[identity] = proposal
                continue
            current = index[identity]
            current_roles = {str(role) for role in current.metadata.get("support_roles", [])}
            extra_roles = {str(role) for role in proposal.metadata.get("support_roles", [])}
            current.metadata["support_roles"] = sorted(current_roles | extra_roles)
            if "rationale" not in current.payload and proposal.payload.get("rationale"):
                current.payload["rationale"] = proposal.payload["rationale"]
        return merged

    def _proposal_identity(self, proposal: ProposalRecord) -> tuple[str, str, str]:
        payload_keys = {
            "atom": "atom",
            "constraint": "constraint",
            "hidden_variable": "hidden_variable",
            "semantic_label": "label",
            "test": "test",
            "evidence_query": "query",
        }
        payload_key = payload_keys.get(proposal.proposal_type, "")
        value = str(proposal.payload.get(payload_key, "")).strip().lower()
        artifact = str(proposal.payload.get("artifact", "")).strip().lower()
        return proposal.proposal_type, value, artifact

    def _artifacts_from_context(self, context: dict) -> list[dict]:
        artifacts: list[dict] = []
        for manifest_path in context.get("manifest_paths", []):
            artifacts.append({"manifest_path": manifest_path})
        return artifacts

    def _cache_key(self, artifacts: list[dict]) -> str:
        manifest_paths = sorted(
            str(artifact.get("manifest_path"))
            for artifact in artifacts
            if artifact.get("manifest_path") is not None
        )
        return json.dumps(manifest_paths)

    def _filter_proposals(
        self,
        proposals: list[ProposalRecord],
        allowed_types: set[str],
    ) -> list[ProposalRecord]:
        return [proposal for proposal in proposals if proposal.proposal_type in allowed_types]

    def _build_prompt(self, bundles: list[ArtifactBundle], query: str) -> str:
        sections: list[str] = [
            "You are a proposal generator for a contradiction-driven neuro-symbolic system.",
            "Return JSON with keys: atoms, constraints, hidden_variables, semantic_labels, tests, evidence_queries.",
            "Each array item must use exact artifact-native identifiers when they exist.",
            "Only propose candidates grounded in the supplied artifacts. Do not invent support that is not present.",
            "Prefer missing latent state or invariant information from the formal specification over buggy implementation-local variables.",
            "Prefer the minimal high-confidence proposal set that would help verifier-backed structural learning.",
            "For tests, preserve exact failing test names from the artifacts.",
            "For hidden variables, preserve exact formal-spec names when they are absent from source.",
            "For semantic labels, choose short reusable labels that match the structural roles.",
        ]
        if query:
            sections.append(f"Operator query: {query}")
        for bundle in bundles:
            manifest = bundle.manifest
            sections.extend(
                [
                    f"Task: {manifest.get('task_id')}",
                    f"Description: {manifest.get('description')}",
                    f"Natural language spec: {manifest.get('natural_language_spec')}",
                    "Formal rules:",
                    *[
                        f"- {rule}"
                        for rule in manifest.get("formal_spec", {}).get("rules", [])[
                            : self.max_rules
                        ]
                    ],
                    f"Safety property: {manifest.get('formal_spec', {}).get('safety_property', '')}",
                    "Failing tests:",
                    *[
                        f"- {test.get('name')}: {' '.join(str(token) for token in test.get('trace', []))}"
                        for test in manifest.get("failing_tests", [])[: self.max_failing_tests]
                    ],
                    "Counterexamples:",
                    *[
                        f"- {counterexample.get('name')}: {' '.join(str(token) for token in counterexample.get('trace', []))}"
                        for counterexample in manifest.get("counterexamples", [])[
                            : self.max_counterexamples
                        ]
                    ],
                    "Logs:",
                    *[
                        f"- {log_entry.get('level')}: {log_entry.get('message')} :: {' '.join(str(token) for token in log_entry.get('trace', []))}"
                        for log_entry in manifest.get("logs", [])[: self.max_logs]
                    ],
                    f"Source variables: {', '.join(bundle.source_variables[: self.max_source_variables])}",
                    "Source excerpt:",
                    bundle.source_text[: self.source_excerpt_chars],
                ]
            )
        sections.extend(
            [
                "Output constraints:",
                "- atoms: at most 1 entry",
                "- constraints: at most 1 entry",
                "- hidden_variables: at most 1 entry",
                "- semantic_labels: at most 1 entry",
                "- tests: at most 2 entries",
                "- evidence_queries: at most 1 entry",
                "If a category has no strong grounded candidate, return an empty array for that category.",
            ]
        )
        return "\n".join(sections)

    def _request_json(self, prompt: str) -> dict[str, Any]:
        try:
            return self._request_json_once(prompt, mode=self.response_format_mode)
        except RuntimeError as exc:
            if self.response_format_mode == "json_schema" and (
                "json_validate_failed" in str(exc) or _should_retry_with_json_object(str(exc))
            ):
                repair_prompt = (
                    f"{prompt}\n"
                    "Repair note: return all six top-level arrays even when a category is empty."
                )
                return self._request_json_once(repair_prompt, mode="json_object")
            raise

    def _request_json_once(
        self,
        prompt: str,
        mode: str,
        *,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        active_model = model_override or self.model
        response_format: dict[str, Any]
        if mode == "json_schema":
            response_format = self._proposal_json_schema()
        else:
            response_format = {"type": "json_object"}
        payload = {
            "model": active_model,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": response_format,
            "messages": [
                {
                    "role": "system",
                    "content": "You produce structured JSON only.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {os.environ[self.api_key_env]}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36 densn-atlas/0.1"
                ),
            },
            method="POST",
        )
        max_attempts = max(self.max_attempts, 1)
        for attempt in range(max_attempts):
            attempt_index = attempt + 1
            request_started_at = time.perf_counter()
            self._trace_request(
                {
                    "event": "request_started",
                    "attempt": attempt_index,
                    "max_attempts": max_attempts,
                    "mode": mode,
                    "prompt_chars": len(prompt),
                    "model": active_model,
                }
            )
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self._trace_request(
                        {
                            "event": "request_succeeded",
                            "attempt": attempt_index,
                            "max_attempts": max_attempts,
                            "mode": mode,
                            "prompt_chars": len(prompt),
                            "model": active_model,
                            "elapsed_seconds": round(time.perf_counter() - request_started_at, 3),
                        }
                    )
                    return payload
            except error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                self._trace_request(
                    {
                        "event": "request_http_error",
                        "attempt": attempt_index,
                        "max_attempts": max_attempts,
                        "mode": mode,
                        "model": active_model,
                        "status_code": exc.code,
                        "elapsed_seconds": round(time.perf_counter() - request_started_at, 3),
                    }
                )
                if exc.code == 429 and attempt_index < max_attempts:
                    retry_after = min(
                        self._retry_after_seconds(details, exc.headers.get("retry-after")),
                        self.max_retry_after_seconds,
                    )
                    self._trace_request(
                        {
                            "event": "request_retry_sleep",
                            "attempt": attempt_index,
                            "sleep_seconds": retry_after,
                            "mode": mode,
                            "model": active_model,
                        }
                    )
                    time.sleep(retry_after)
                    continue
                raise RuntimeError(
                    f"Transformer request failed: HTTP {exc.code}: {details}"
                ) from exc
            except error.URLError as exc:
                self._trace_request(
                    {
                        "event": "request_url_error",
                        "attempt": attempt_index,
                        "max_attempts": max_attempts,
                        "mode": mode,
                        "model": active_model,
                        "elapsed_seconds": round(time.perf_counter() - request_started_at, 3),
                        "reason": str(exc.reason),
                    }
                )
                raise RuntimeError(f"Transformer request failed: {exc.reason}") from exc
        raise RuntimeError("Transformer request failed after retry budget was exhausted.")

    def _trace_request(self, payload: dict[str, Any]) -> None:
        if not self.request_trace_path:
            return
        trace_path = Path(self.request_trace_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def _retry_after_seconds(self, details: str, retry_after_header: str | None) -> float:
        if retry_after_header:
            try:
                return max(float(retry_after_header), 1.0)
            except ValueError:
                pass
        match = re.search(r"try again in ([0-9]+(?:\\.[0-9]+)?)s", details, flags=re.IGNORECASE)
        if match:
            return max(float(match.group(1)) + 0.5, 1.0)
        return 3.0

    def _parse_response_json(self, raw: dict[str, Any]) -> dict[str, Any]:
        choices = raw.get("choices", [])
        if not choices:
            raise RuntimeError("Transformer response contained no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Transformer response did not contain text content.")
        return json.loads(content)

    def _proposal_json_schema(self) -> dict[str, Any]:
        def item_schema(value_key: str) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {
                    value_key: {"type": "string"},
                    "artifact": {"type": "string"},
                    "rationale": {"type": "string"},
                    "support_roles": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [value_key, "artifact", "rationale", "support_roles"],
                "additionalProperties": False,
            }

        return {
            "type": "json_schema",
            "json_schema": {
                "name": "densn_proposals",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "atoms": {"type": "array", "items": item_schema("atom")},
                        "constraints": {"type": "array", "items": item_schema("constraint")},
                        "hidden_variables": {
                            "type": "array",
                            "items": item_schema("hidden_variable"),
                        },
                        "semantic_labels": {
                            "type": "array",
                            "items": item_schema("label"),
                        },
                        "tests": {"type": "array", "items": item_schema("test")},
                        "evidence_queries": {
                            "type": "array",
                            "items": item_schema("query"),
                        },
                    },
                    "required": [
                        "atoms",
                        "constraints",
                        "hidden_variables",
                        "semantic_labels",
                        "tests",
                        "evidence_queries",
                    ],
                    "additionalProperties": False,
                },
            },
        }

    def _records_from_payload(
        self,
        payload: dict[str, Any],
        task_id: str | None,
        allowed_types: set[str] | None = None,
    ) -> list[ProposalRecord]:
        specs = (
            ("atoms", "atom", "atom"),
            ("constraints", "constraint", "constraint"),
            ("hidden_variables", "hidden_variable", "hidden_variable"),
            ("semantic_labels", "semantic_label", "label"),
            ("tests", "test", "test"),
            ("evidence_queries", "evidence_query", "query"),
        )
        proposals: list[ProposalRecord] = []
        for collection_name, proposal_type, payload_key in specs:
            if allowed_types is not None and proposal_type not in allowed_types:
                continue
            items = payload.get(collection_name, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or payload_key not in item:
                    continue
                proposal_payload = {payload_key: item[payload_key]}
                if "artifact" in item:
                    proposal_payload["artifact"] = item["artifact"]
                if "rationale" in item:
                    proposal_payload["rationale"] = item["rationale"]
                declared_roles = item.get("support_roles", [])
                support_roles = sorted(
                    {
                        *[str(role) for role in declared_roles if str(role)],
                        *[
                            token
                            for token in normalize_tokens(json.dumps(item, sort_keys=True))
                            if token
                            in {
                                "open",
                                "close",
                                "write",
                                "guard",
                                "begin",
                                "end",
                                "action",
                                "prepare",
                                "commit",
                                "pending",
                                "ack",
                                "clear",
                            }
                        ],
                    }
                )
                proposals.append(
                    ProposalRecord(
                        id=f"proposal_{uuid4().hex[:8]}",
                        proposal_type=proposal_type,
                        source=self.source_name,
                        payload=proposal_payload,
                        task_id=task_id,
                        metadata={"support_roles": support_roles},
                    )
                )
        return proposals


class GroqQuotaLedger:
    """Best-effort local quota tracker for Groq model limits."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.state = self._load()

    def can_run(self, model: str, estimated_tokens: int) -> tuple[bool, str | None]:
        profile = GROQ_MODEL_LIMITS.get(model)
        if profile is None:
            return True, None
        now = time.time()
        record = self._normalized_record(model, now=now)
        if float(record.get("blocked_until_epoch", 0.0) or 0.0) > now:
            return False, "blocked_until_retry_after"
        if self._would_exceed(int(record.get("requests_today", 0)), 1, profile.get("rpd")):
            return False, "requests_per_day"
        if self._would_exceed(
            int(record.get("tokens_today", 0)), estimated_tokens, profile.get("tpd")
        ):
            return False, "tokens_per_day"
        if self._would_exceed(int(record.get("requests_minute", 0)), 1, profile.get("rpm")):
            return False, "requests_per_minute"
        if self._would_exceed(
            int(record.get("tokens_minute", 0)), estimated_tokens, profile.get("tpm")
        ):
            return False, "tokens_per_minute"
        return True, None

    def reserve(self, model: str, estimated_tokens: int) -> None:
        now = time.time()
        record = self._normalized_record(model, now=now)
        record["requests_today"] = int(record.get("requests_today", 0)) + 1
        record["tokens_today"] = int(record.get("tokens_today", 0)) + estimated_tokens
        record["requests_minute"] = int(record.get("requests_minute", 0)) + 1
        record["tokens_minute"] = int(record.get("tokens_minute", 0)) + estimated_tokens
        self._store(model, record)

    def finalize(self, model: str, estimated_tokens: int, actual_total_tokens: int | None) -> None:
        if actual_total_tokens is None:
            return
        record = self._normalized_record(model)
        delta = int(actual_total_tokens) - int(estimated_tokens)
        if delta == 0:
            return
        record["tokens_today"] = max(0, int(record.get("tokens_today", 0)) + delta)
        record["tokens_minute"] = max(0, int(record.get("tokens_minute", 0)) + delta)
        self._store(model, record)

    def apply_rate_limit_feedback(
        self, model: str, details: str, retry_after_seconds: float
    ) -> None:
        record = self._normalized_record(model)
        limit_match = re.search(
            r"Limit\s+([0-9]+),\s+Used\s+([0-9]+),\s+Requested\s+([0-9]+)",
            details,
            flags=re.IGNORECASE,
        )
        limit_type_match = re.search(
            r"rate limit reached.*?\((TPD|TPM|RPD|RPM)\)", details, flags=re.IGNORECASE
        )
        rate_limit_type = limit_type_match.group(1).lower() if limit_type_match else ""
        if limit_match:
            limit = int(limit_match.group(1))
            used = int(limit_match.group(2))
            requested = int(limit_match.group(3))
            if rate_limit_type in {"tpd", "tokens"} or "tokens per day" in details.lower():
                record["tokens_today"] = max(
                    int(record.get("tokens_today", 0)), min(limit, used + requested)
                )
            elif rate_limit_type == "rpd" or "requests per day" in details.lower():
                record["requests_today"] = max(
                    int(record.get("requests_today", 0)), min(limit, used + 1)
                )
            elif rate_limit_type == "tpm" or "tokens per minute" in details.lower():
                record["tokens_minute"] = max(
                    int(record.get("tokens_minute", 0)), min(limit, used + requested)
                )
            elif rate_limit_type == "rpm" or "requests per minute" in details.lower():
                record["requests_minute"] = max(
                    int(record.get("requests_minute", 0)), min(limit, used + 1)
                )
        record["blocked_until_epoch"] = max(
            float(record.get("blocked_until_epoch", 0.0) or 0.0),
            time.time() + max(retry_after_seconds, 1.0),
        )
        self._store(model, record)

    def summary(self) -> dict[str, Any]:
        return self.state

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"models": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"models": {}}

    def _store(self, model: str, record: dict[str, Any]) -> None:
        models = dict(self.state.get("models", {}))
        models[model] = record
        self.state["models"] = models
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _normalized_record(self, model: str, *, now: float | None = None) -> dict[str, Any]:
        current_time = now if now is not None else time.time()
        day_key = time.strftime("%Y-%m-%d", time.gmtime(current_time))
        minute_key = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(current_time))
        record = dict(self.state.get("models", {}).get(model, {}))
        if record.get("day_key") != day_key:
            record["day_key"] = day_key
            record["requests_today"] = 0
            record["tokens_today"] = 0
        if record.get("minute_key") != minute_key:
            record["minute_key"] = minute_key
            record["requests_minute"] = 0
            record["tokens_minute"] = 0
        record.setdefault("blocked_until_epoch", 0.0)
        return record

    def _would_exceed(self, used: int, delta: int, limit: int | None) -> bool:
        if limit is None:
            return False
        return used + delta > int(limit)


def groq_model_candidates(primary_model: str | None = None) -> list[str]:
    configured = os.getenv("DENSN_GROQ_MODEL_CANDIDATES", "")
    items = [item.strip() for item in configured.split(",") if item.strip()]
    ordered = items or [primary_model or "", *DEFAULT_GROQ_MODEL_CANDIDATES]
    candidates: list[str] = []
    for item in ordered:
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def estimated_total_tokens(prompt: str, max_completion_tokens: int) -> int:
    prompt_tokens = max(1, (len(prompt) + 3) // 4)
    return int(prompt_tokens + max_completion_tokens)


def _response_usage_total_tokens(payload: dict[str, Any]) -> int | None:
    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if total is None:
        completion = usage.get("completion_tokens")
        prompt = usage.get("prompt_tokens")
        if completion is not None and prompt is not None:
            total = int(completion) + int(prompt)
    if total is None:
        return None
    try:
        return int(total)
    except (TypeError, ValueError):
        return None


def _should_retry_with_json_object(message: str) -> bool:
    lowered = message.lower()
    return (
        "json_schema" in lowered
        or "response_format" in lowered
        or "unsupported" in lowered
        or "schema" in lowered
    )


class GroqChatTransformerAdapter(OpenAIChatTransformerAdapter):
    """Groq OpenAI-compatible chat-completions adapter."""

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
        max_completion_tokens: int = 700,
        response_format_mode: str = "json_schema",
    ) -> None:
        super().__init__(
            model=model or os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b",
            api_key_env="GROQ_API_KEY",
            base_url=os.getenv("GROQ_BASE_URL")
            or "https://api.groq.com/openai/v1/chat/completions",
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            response_format_mode=response_format_mode,
        )
        self.source_name = "groq_chat_adapter"
        ledger_path = os.getenv("DENSN_GROQ_QUOTA_LEDGER_PATH") or str(
            Path("artifacts") / "runtime" / "groq_quota_ledger.json"
        )
        self.quota_ledger = GroqQuotaLedger(ledger_path)
        self.candidate_models = groq_model_candidates(self.model)

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["candidate_models"] = list(self.candidate_models)
        base["quota_ledger_path"] = str(self.quota_ledger.path)
        return base

    def _request_json(self, prompt: str) -> dict[str, Any]:
        estimated_tokens = estimated_total_tokens(prompt, self.max_completion_tokens)
        available_candidates: list[str] = []
        local_block_reasons: dict[str, str] = {}
        for candidate in self.candidate_models:
            allowed, reason = self.quota_ledger.can_run(candidate, estimated_tokens)
            if allowed:
                available_candidates.append(candidate)
            elif reason:
                local_block_reasons[candidate] = reason
        if not available_candidates:
            raise RuntimeError(
                "Groq local quota ledger found no candidate model within configured limits: "
                + json.dumps(local_block_reasons, sort_keys=True)
            )

        last_error: RuntimeError | None = None
        for candidate in available_candidates:
            for mode in self._candidate_modes_for_model(candidate):
                self.quota_ledger.reserve(candidate, estimated_tokens)
                try:
                    raw = self._request_json_once(prompt, mode=mode, model_override=candidate)
                    self.quota_ledger.finalize(
                        candidate,
                        estimated_tokens,
                        _response_usage_total_tokens(raw),
                    )
                    self.model = candidate
                    return raw
                except RuntimeError as exc:
                    last_error = exc
                    message = str(exc)
                    if "HTTP 429" in message:
                        retry_after = min(
                            self._retry_after_seconds(message, None),
                            self.max_retry_after_seconds,
                        )
                        self.quota_ledger.apply_rate_limit_feedback(candidate, message, retry_after)
                        break
                    if mode == "json_schema" and _should_retry_with_json_object(message):
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("Groq request failed before any candidate model completed.")

    def _candidate_modes(self) -> list[str]:
        if self.response_format_mode == "json_schema":
            return ["json_schema", "json_object"]
        return [self.response_format_mode]

    def _candidate_modes_for_model(self, model: str) -> list[str]:
        configured = GROQ_MODEL_RESPONSE_MODES.get(model)
        if configured:
            return list(configured)
        return self._candidate_modes()


def build_transformer_adapter_from_env(
    fallback: TransformerAdapter | None = None,
) -> TransformerAdapter | None:
    if os.getenv("GROQ_API_KEY"):
        return GroqChatTransformerAdapter()
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIChatTransformerAdapter()
    return fallback


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
