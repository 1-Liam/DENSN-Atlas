"""Generate publication-grade provenance for the DENSN proof bundle."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import (
    artifact_version_info,
    git_sha,
    write_json_artifact,
    write_text_artifact,
)

ARTIFACT_PATHS = {
    "gauntlet": ROOT / "artifacts" / "phase7" / "gauntlet_summary.json",
    "pathway_a": ROOT / "artifacts" / "phase8" / "pathway_a_summary.json",
    "verifier_agreement": ROOT / "artifacts" / "phase9" / "verifier_agreement_summary.json",
    "proposal_quality": ROOT / "artifacts" / "phase2" / "proposal_quality_summary.json",
    "proposal_precision": ROOT / "artifacts" / "phase13" / "proposal_precision_summary.json",
    "protocol_runtime": ROOT / "artifacts" / "phase2" / "proposal_runtime_summary.json",
    "quorum_runtime": ROOT / "artifacts" / "phase4" / "quorum_proposal_runtime_summary.json",
}

VERIFIER_PATHS = [
    ROOT / "verifiers" / "protocol_guard_verifier.py",
    ROOT / "verifiers" / "lease_lock_verifier.py",
    ROOT / "verifiers" / "session_epoch_verifier.py",
    ROOT / "verifiers" / "quorum_commit_verifier.py",
    ROOT / "verifiers" / "vote_majority_commit_verifier.py",
    ROOT / "verifiers" / "replication_barrier_verifier.py",
    ROOT / "verifiers" / "session_macro_verifier.py",
]

FIXTURE_ROOTS = [
    ROOT / "fixtures" / "protocol_guard",
    ROOT / "fixtures" / "lease_lock",
    ROOT / "fixtures" / "session_epoch",
    ROOT / "fixtures" / "quorum_commit",
    ROOT / "fixtures" / "vote_majority_commit",
    ROOT / "fixtures" / "replication_barrier",
    ROOT / "fixtures" / "session_macro",
]

COMMANDS_USED = [
    "python scripts/run_proposal_quality.py protocol_guard",
    "python scripts/run_proposal_runtime.py protocol_guard",
    "python scripts/run_quorum_proposal_runtime.py",
    "python scripts/run_proposal_precision_campaign.py --family protocol_guard --fixed-pool-source artifacts/phase2/proposal_quality_summary.json",
    "python scripts/run_proposal_precision_campaign.py --refresh-pool",
    "python scripts/run_gauntlet.py",
    "python scripts/run_gauntlet_report.py",
    "python scripts/run_pathway_a.py",
    "python scripts/run_verifier_agreement.py",
    "python scripts/run_proof_manifest.py",
    "python scripts/run_final_proof_bundle.py",
]

SOURCE_DIRTY_EXCLUDES = [
    ":(exclude)artifacts/**",
    ":(exclude)reports/**",
    ":(exclude)repro/environment_manifest.json",
    ":(exclude)repro/expected_metrics.json",
]


def commands_used() -> list[str]:
    raw = os.getenv("DENSN_COMMANDS_USED_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                return list(parsed)
        except json.JSONDecodeError:
            pass
    return list(COMMANDS_USED)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def file_manifest(paths: list[Path]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        manifest.append(
            {
                "path": repo_relative(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return manifest


def git_dirty(root: Path, *, exclude_generated: bool = False) -> bool:
    command = ["git", "status", "--porcelain", "--", "."]
    if exclude_generated:
        command.extend(SOURCE_DIRTY_EXCLUDES)
    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=5.0,
        )
    except Exception:
        return True
    return bool(result.stdout.strip())


def artifact_core_frozen(artifact: dict[str, Any]) -> bool:
    if not artifact:
        return False
    proof_contract = artifact.get("proof_contract", {})
    if isinstance(proof_contract, dict) and proof_contract:
        return proof_contract.get("core_mode") == "core_frozen"
    variants = artifact.get("variants")
    if isinstance(variants, list) and variants:
        nested_contracts: list[dict[str, Any]] = []
        for variant in variants:
            quality_contract = (
                variant.get("quality_summary", {}).get("proof_contract", {})
                if isinstance(variant, dict)
                else {}
            )
            runtime_contract = (
                variant.get("runtime_summary", {}).get("proof_contract", {})
                if isinstance(variant, dict)
                else {}
            )
            if isinstance(quality_contract, dict) and quality_contract:
                nested_contracts.append(quality_contract)
            if isinstance(runtime_contract, dict) and runtime_contract:
                nested_contracts.append(runtime_contract)
        if nested_contracts:
            return all(contract.get("core_mode") == "core_frozen" for contract in nested_contracts)
    rows = artifact.get("rows")
    if isinstance(rows, list) and rows:
        return all(row.get("core_mode") == "core_frozen" for row in rows if "core_mode" in row)
    return False


def fixture_manifest() -> list[dict[str, Any]]:
    files: list[Path] = []
    for root in FIXTURE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append(path)
    return file_manifest(files)


def build_summary(version: dict[str, str]) -> dict[str, Any]:
    artifacts = {name: load_json(path) for name, path in ARTIFACT_PATHS.items()}
    dirty_full = git_dirty(ROOT)
    dirty_source = git_dirty(ROOT, exclude_generated=True)
    return {
        "artifact_version": version,
        "git_sha": git_sha(ROOT),
        "git_dirty": dirty_source,
        "git_dirty_source": dirty_source,
        "git_dirty_full": dirty_full,
        "git_dirty_source_excludes": [
            "artifacts/**",
            "reports/**",
            "repro/environment_manifest.json",
            "repro/expected_metrics.json",
        ],
        "timestamp_utc": version["timestamp_utc"],
        "commands_used": commands_used(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "environment_manifest": {
            "cwd": ".",
            "groq_model": os.getenv("GROQ_MODEL"),
            "groq_api_key_present": bool(os.getenv("GROQ_API_KEY")),
            "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY")),
        },
        "model_backend_manifest": {
            "backend": "Groq OpenAI-compatible API",
            "model_name": os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b",
            "adapter": "GroqChatTransformerAdapter",
        },
        "artifact_versions": {
            name: artifact.get("artifact_version") for name, artifact in artifacts.items()
        },
        "verifier_manifest": file_manifest(VERIFIER_PATHS),
        "fixture_hashes": fixture_manifest(),
        "core_frozen": all(
            artifact_core_frozen(artifact) for artifact in artifacts.values() if artifact
        ),
    }


def markdown_from_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Proof Manifest",
        "",
        f"- git_sha: `{summary['git_sha']}`",
        f"- timestamp_utc: `{summary['timestamp_utc']}`",
        f"- python_version: `{summary['python_version']}`",
        f"- model_name: `{summary['model_backend_manifest']['model_name']}`",
        f"- git_dirty_source: `{summary['git_dirty_source']}`",
        f"- git_dirty_full: `{summary['git_dirty_full']}`",
        f"- core_frozen: `{summary['core_frozen']}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    version = artifact_version_info("phase10", root=ROOT)
    summary = build_summary(version)
    write_json_artifact(
        ROOT / "artifacts" / "phase10" / "proof_manifest.json", summary, version=version
    )
    write_text_artifact(
        ROOT / "reports" / "phase10_proof_manifest_report.md",
        markdown_from_summary(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
