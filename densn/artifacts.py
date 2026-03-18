"""Artifact manifest ingestion for formal-task evidence and provenance."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .graph import PersistentGraph
from .records import Edge, Evidence, Task

ARTIFACT_KEYS = (
    "natural_language_spec",
    "formal_spec",
    "execution_traces",
    "failing_tests",
    "logs",
    "counterexamples",
    "source_code_path",
)


TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ArtifactBundle:
    manifest_path: str
    manifest: dict[str, Any]
    source_path: str | None
    source_text: str
    source_variables: list[str]
    role_aliases: dict[str, list[str]]
    support_role_index: dict[str, list[str]]
    vocabulary: list[str]
    failing_test_names: list[str]
    counterexample_names: list[str]


def normalize_tokens(text: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [token for token in TOKEN_SPLIT_RE.split(normalized.lower()) if token]


def source_variables_from_text(source_text: str, filename: str = "<source>") -> list[str]:
    try:
        tree = ast.parse(source_text, filename=filename)
    except SyntaxError:
        return []
    variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            variables.add(node.id)
    return sorted(variables)


def load_manifest(path: str | Path) -> dict[str, Any]:
    return _load_manifest_cached(str(Path(path).resolve()))


@lru_cache(maxsize=256)
def _load_manifest_cached(resolved_path: str) -> dict[str, Any]:
    manifest_path = Path(resolved_path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_artifact_bundle(path: str | Path) -> ArtifactBundle:
    return _load_artifact_bundle_cached(str(Path(path).resolve()))


@lru_cache(maxsize=256)
def _load_artifact_bundle_cached(resolved_path: str) -> ArtifactBundle:
    manifest_path = Path(resolved_path)
    manifest = load_manifest(manifest_path)

    source_path: Path | None = None
    source_text = ""
    if "source_code_path" in manifest:
        source_path = (manifest_path.parent / str(manifest["source_code_path"])).resolve()
        source_text = source_path.read_text(encoding="utf-8")

    role_alias_sets: dict[str, set[str]] = {}
    roles = manifest.get("roles", {})
    canonical_roles = manifest.get("canonical_roles", {})
    for role_name, token in roles.items():
        aliases = set(normalize_tokens(str(role_name)))
        aliases.update(normalize_tokens(str(token)))
        aliases.update(normalize_tokens(str(canonical_roles.get(role_name, role_name))))
        role_alias_sets[str(role_name)] = aliases

    support_role_index: dict[str, set[str]] = {}
    for role_name, aliases in role_alias_sets.items():
        for alias in aliases:
            support_role_index.setdefault(alias, set()).add(role_name)

    for rule in manifest.get("formal_spec", {}).get("rules", []):
        rule_tokens = set(normalize_tokens(str(rule)))
        rule_roles: set[str] = set()
        for role_name, aliases in role_alias_sets.items():
            if aliases & rule_tokens:
                rule_roles.add(role_name)
        for token in rule_tokens:
            support_role_index.setdefault(token, set()).update(rule_roles)

    vocabulary: set[str] = set()
    for key in ("description", "natural_language_spec"):
        vocabulary.update(normalize_tokens(str(manifest.get(key, ""))))
    for rule in manifest.get("formal_spec", {}).get("rules", []):
        vocabulary.update(normalize_tokens(str(rule)))
    for trace in manifest.get("execution_traces", []):
        vocabulary.update(normalize_tokens(" ".join(str(token) for token in trace)))
    failing_test_names: list[str] = []
    for test in manifest.get("failing_tests", []):
        name = str(test.get("name", ""))
        if name:
            failing_test_names.append(name)
            vocabulary.update(normalize_tokens(name))
        vocabulary.update(normalize_tokens(" ".join(str(token) for token in test.get("trace", []))))
    counterexample_names: list[str] = []
    for counterexample in manifest.get("counterexamples", []):
        name = str(counterexample.get("name", ""))
        if name:
            counterexample_names.append(name)
            vocabulary.update(normalize_tokens(name))
        vocabulary.update(
            normalize_tokens(" ".join(str(token) for token in counterexample.get("trace", [])))
        )
        vocabulary.update(normalize_tokens(str(counterexample.get("reason", ""))))
    for log_entry in manifest.get("logs", []):
        vocabulary.update(normalize_tokens(str(log_entry.get("message", ""))))
        vocabulary.update(
            normalize_tokens(" ".join(str(token) for token in log_entry.get("trace", [])))
        )
    vocabulary.update(normalize_tokens(source_text))
    source_variables = source_variables_from_text(
        source_text, filename=str(source_path or manifest_path)
    )
    for variable in source_variables:
        vocabulary.update(normalize_tokens(variable))

    return ArtifactBundle(
        manifest_path=str(manifest_path),
        manifest=manifest,
        source_path=None if source_path is None else str(source_path),
        source_text=source_text,
        source_variables=source_variables,
        role_aliases={role: sorted(aliases) for role, aliases in role_alias_sets.items()},
        support_role_index={token: sorted(roles) for token, roles in support_role_index.items()},
        vocabulary=sorted(vocabulary),
        failing_test_names=sorted(failing_test_names),
        counterexample_names=sorted(counterexample_names),
    )


def attach_artifact_manifest(
    graph: PersistentGraph,
    manifest_path: str | Path,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    task = Task(
        id=manifest["task_id"],
        family=manifest["family"],
        split=manifest["split"],
        description=manifest["description"],
        metadata={"manifest_path": str(manifest_path)},
    )
    graph.add_node(task)

    evidence_ids: dict[str, str] = {}
    for key in ARTIFACT_KEYS:
        if key not in manifest:
            continue
        content = manifest[key]
        if key == "source_code_path":
            source_path = (manifest_path.parent / str(content)).resolve()
            content_ref = str(source_path)
            metadata = {"path": str(source_path)}
        else:
            content_ref = f"{manifest_path}#{key}"
            metadata = {"inline": True}
        evidence = Evidence(
            id=graph.next_id("evidence"),
            kind=key,
            content_ref=content_ref,
            source="artifact_manifest",
            task_id=task.id,
            metadata=metadata,
        )
        graph.add_node(evidence)
        graph.add_edge(
            Edge(
                id=graph.next_id("edge"),
                src_id=evidence.id,
                dst_id=task.id,
                edge_kind="provenance_of",
            )
        )
        evidence_ids[key] = evidence.id

    return {
        "task_id": task.id,
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "evidence_ids": evidence_ids,
    }


def link_provenance(
    graph: PersistentGraph,
    evidence_ids: list[str],
    node_ids: list[str],
) -> None:
    for evidence_id in evidence_ids:
        if evidence_id not in graph.nodes:
            continue
        for node_id in node_ids:
            if node_id not in graph.nodes:
                continue
            graph.add_edge(
                Edge(
                    id=graph.next_id("edge"),
                    src_id=evidence_id,
                    dst_id=node_id,
                    edge_kind="provenance_of",
                )
            )
