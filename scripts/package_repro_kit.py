"""Package a reproducibility kit around the current canonical proof bundle."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact

REPRO_DIR = ROOT / "repro"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    version = artifact_version_info("phase12", root=ROOT)
    REPRO_DIR.mkdir(parents=True, exist_ok=True)

    final_bundle = _load_json(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json")
    proof_manifest = _load_json(ROOT / "artifacts" / "phase10" / "proof_manifest.json")
    gauntlet = _load_json(ROOT / "artifacts" / "phase7" / "gauntlet_summary.json")
    pathway_a = _load_json(ROOT / "artifacts" / "phase8" / "pathway_a_summary.json")
    verifier_agreement = _load_json(
        ROOT / "artifacts" / "phase9" / "verifier_agreement_summary.json"
    )

    expected_metrics = {
        "canonical_bundle_path": _repo_relative(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json"),
        "headline_checks": final_bundle.get("checks", {}),
        "pathway_b": final_bundle.get("pathway_b_proof", {}),
        "gauntlet": {
            "positive_transfer_count": gauntlet.get("metrics", {}).get("positive_transfer_count"),
            "cross_mechanism_block_count": gauntlet.get("metrics", {}).get(
                "cross_mechanism_block_count"
            ),
        },
        "pathway_a": {
            "compression_gain": pathway_a.get("compression_gain"),
            "downstream_cycles_reduction": pathway_a.get("downstream_cycles_reduction"),
            "downstream_verifier_calls_reduction": pathway_a.get(
                "downstream_verifier_calls_reduction"
            ),
        },
        "live_model": final_bundle.get("live_model_contribution", {}),
        "verifier_reliability": {
            "effective_agreement_quality": verifier_agreement.get("effective_agreement_quality"),
            "unresolved_disagreement_count": verifier_agreement.get(
                "unresolved_disagreement_count"
            ),
        },
    }
    environment_manifest = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "required_env": ["GROQ_API_KEY"],
        "optional_env": ["GROQ_MODEL", "GROQ_BASE_URL"],
        "canonical_model_backend": proof_manifest.get("model_backend_manifest"),
    }
    run_script = """param([switch]$FreshLive)\n$ErrorActionPreference = 'Stop'\n\n$envFile = Join-Path $PSScriptRoot \"..\\\\.env\"\nif (Test-Path $envFile) {\n  Get-Content $envFile | ForEach-Object {\n    $line = $_.Trim()\n    if (-not $line -or $line.StartsWith(\"#\")) {\n      return\n    }\n    $parts = $line -split \"=\", 2\n    if ($parts.Count -ne 2) {\n      return\n    }\n    $name = $parts[0].Trim()\n    $value = $parts[1].Trim()\n    if ($name) {\n      [System.Environment]::SetEnvironmentVariable($name, $value, \"Process\")\n    }\n  }\n}\n\nif ($FreshLive) {\n  python scripts/run_fresh_live_bundle.py\n  python scripts/check_phase12_regression.py --baseline artifacts/phase11/final_proof_bundle.json --candidate artifacts/phase12/fresh_live_final_proof_bundle.json\n} else {\n  python scripts/run_proposal_quality.py\n  python scripts/run_proposal_runtime.py\n  python scripts/run_quorum_proposal_runtime.py\n  python scripts/run_gauntlet.py --reuse-existing\n  python scripts/run_gauntlet_report.py\n  python scripts/run_pathway_a.py\n  python scripts/run_verifier_agreement.py\n  python scripts/run_proof_manifest.py\n  python scripts/run_final_proof_bundle.py\n  python scripts/verify_repro_run.py\n}\n"""
    readme = """# DENSN Repro Kit\n\n## Goal\n\nReproduce the current canonical DENSN proof bundle without modifying the frozen core.\n\n## Prerequisites\n\n- Python available on `PATH`\n- `.env.example` copied to `.env`, or `GROQ_API_KEY` set in your shell for live proposal-path scripts\n- Repo checked out at the expected revision or a compatible descendant\n\n## Environment Setup\n\n```powershell\nCopy-Item .env.example .env\n```\n\nThen set your own Groq key in `.env` or in the shell:\n\n```powershell\n$env:GROQ_API_KEY=\"your_key_here\"\n```\n\n## One-Command Repro\n\n```powershell\n./repro/run_repro.ps1\n```\n\nFor a full fresh live attempt instead of the current canonical chain:\n\n```powershell\n./repro/run_repro.ps1 -FreshLive\n```\n\n## Verification\n\nThe repro run ends by executing `python scripts/verify_repro_run.py`, which compares the current outputs against `repro/expected_metrics.json` and emits `artifacts/phase12/repro_verification_summary.json`.\n"""

    _write_text(REPRO_DIR / "README.md", readme)
    _write_text(REPRO_DIR / "run_repro.ps1", run_script)
    _write_text(REPRO_DIR / "expected_metrics.json", json.dumps(expected_metrics, indent=2) + "\n")
    _write_text(
        REPRO_DIR / "environment_manifest.json", json.dumps(environment_manifest, indent=2) + "\n"
    )

    summary = {
        "artifact_version": version,
        "canonical_bundle": _repo_relative(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json"),
        "proof_manifest": _repo_relative(ROOT / "artifacts" / "phase10" / "proof_manifest.json"),
        "gauntlet": _repo_relative(ROOT / "artifacts" / "phase7" / "gauntlet_summary.json"),
        "pathway_a": _repo_relative(ROOT / "artifacts" / "phase8" / "pathway_a_summary.json"),
        "verifier_agreement": _repo_relative(
            ROOT / "artifacts" / "phase9" / "verifier_agreement_summary.json"
        ),
        "repro_files": {
            "readme": _repo_relative(REPRO_DIR / "README.md"),
            "run_script": _repo_relative(REPRO_DIR / "run_repro.ps1"),
            "expected_metrics": _repo_relative(REPRO_DIR / "expected_metrics.json"),
            "environment_manifest": _repo_relative(REPRO_DIR / "environment_manifest.json"),
        },
        "expected_checks": final_bundle.get("checks", {}),
        "fixture_hash_count": len(proof_manifest.get("fixture_hashes", [])),
        "verifier_hash_count": len(proof_manifest.get("verifier_manifest", [])),
    }
    write_json_artifact(
        ROOT / "artifacts" / "phase12" / "repro_kit_manifest.json", summary, version=version
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
