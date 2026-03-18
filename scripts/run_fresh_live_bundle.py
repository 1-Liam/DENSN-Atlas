"""Run the full fresh-live Phase 12 proof chain and emit a blocker-aware manifest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from densn.artifact_store import artifact_version_info, write_json_artifact, write_text_artifact

OUTPUT_DIR = ROOT / "artifacts" / "phase12"
MANIFEST_PATH = OUTPUT_DIR / "fresh_live_run_manifest.json"
GAUNTLET_ALIAS_PATH = OUTPUT_DIR / "fresh_live_gauntlet_summary.json"
FINAL_BUNDLE_ALIAS_PATH = OUTPUT_DIR / "fresh_live_final_proof_bundle.json"
STAGES: list[dict[str, Any]] = [
    {
        "name": "proposal_quality_protocol",
        "command": [sys.executable, "scripts/run_proposal_quality.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "proposal_runtime_protocol",
        "command": [sys.executable, "scripts/run_proposal_runtime.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "proposal_runtime_quorum",
        "command": [sys.executable, "scripts/run_quorum_proposal_runtime.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "proposal_precision_campaign",
        "command": [sys.executable, "scripts/run_proposal_precision_campaign.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "gauntlet",
        "command": [sys.executable, "scripts/run_gauntlet.py"],
        "timeout_seconds": 900.0,
    },
    {
        "name": "gauntlet_report",
        "command": [sys.executable, "scripts/run_gauntlet_report.py"],
        "timeout_seconds": 180.0,
    },
    {
        "name": "pathway_a",
        "command": [sys.executable, "scripts/run_pathway_a.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "verifier_agreement",
        "command": [sys.executable, "scripts/run_verifier_agreement.py"],
        "timeout_seconds": 300.0,
    },
    {
        "name": "proof_manifest",
        "command": [sys.executable, "scripts/run_proof_manifest.py"],
        "timeout_seconds": 120.0,
    },
    {
        "name": "final_proof_bundle",
        "command": [sys.executable, "scripts/run_final_proof_bundle.py"],
        "timeout_seconds": 120.0,
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(target: Path, payload: dict[str, Any], *, version: dict[str, str]) -> None:
    write_json_artifact(target, payload, version=version)


def _report_markdown(summary: dict[str, Any]) -> str:
    blocker = summary.get("blocker")
    lines = [
        "# Phase 12 Fresh Live",
        "",
        f"- completed: `{summary.get('completed', False)}`",
        f"- fresh_bundle_ready: `{summary.get('fresh_bundle_ready', False)}`",
        f"- stage_count: `{len(summary.get('stages', []))}`",
    ]
    if blocker:
        lines.append(f"- blocker_kind: `{blocker.get('kind')}`")
        lines.append(f"- blocker_reason: `{blocker.get('reason')}`")
        if blocker.get("stage"):
            lines.append(f"- blocker_stage: `{blocker.get('stage')}`")
    return "\n".join(lines) + "\n"


def _classify_blocker(result: dict[str, Any]) -> dict[str, Any]:
    stderr = str(result.get("stderr", ""))
    stdout = str(result.get("stdout", ""))
    combined = f"{stdout}\n{stderr}"
    if result.get("timeout"):
        return {
            "kind": "command_timeout",
            "reason": "A live proof-chain command exceeded the orchestration timeout.",
            "command": result.get("command"),
            "stage": result.get("stage"),
            "timeout_seconds": result.get("timeout_seconds"),
            "stage_trace_path": result.get("stage_trace_path"),
            "stage_trace": result.get("stage_trace"),
            "request_trace_path": result.get("request_trace_path"),
        }
    if "HTTP 429" in combined or "rate_limit_exceeded" in combined:
        return {
            "kind": "live_model_rate_limit",
            "reason": "Groq rate limit prevented a fully fresh live rerun.",
            "command": result.get("command"),
            "stage": result.get("stage"),
            "stage_trace_path": result.get("stage_trace_path"),
            "stage_trace": result.get("stage_trace"),
            "request_trace_path": result.get("request_trace_path"),
        }
    return {
        "kind": "command_failure",
        "reason": "A proof-chain command failed before the fresh canonical bundle completed.",
        "command": result.get("command"),
        "stage": result.get("stage"),
        "stage_trace_path": result.get("stage_trace_path"),
        "stage_trace": result.get("stage_trace"),
        "request_trace_path": result.get("request_trace_path"),
    }


def _stage_trace_path(stage_name: str) -> Path:
    return OUTPUT_DIR / f"{stage_name}_stage_trace.json"


def _live_stage_env(stage_name: str) -> dict[str, str]:
    env = dict(os.environ)
    request_trace_path = OUTPUT_DIR / f"{stage_name}_request_trace.jsonl"
    command_manifest = json.dumps([" ".join(stage["command"]) for stage in STAGES])
    env.update(
        {
            "DENSN_TRANSFORMER_TIMEOUT_SECONDS": env.get("DENSN_TRANSFORMER_TIMEOUT_SECONDS", "45"),
            "DENSN_TRANSFORMER_MAX_ATTEMPTS": env.get("DENSN_TRANSFORMER_MAX_ATTEMPTS", "1"),
            "DENSN_TRANSFORMER_MAX_RETRY_AFTER_SECONDS": env.get(
                "DENSN_TRANSFORMER_MAX_RETRY_AFTER_SECONDS",
                "2",
            ),
            "DENSN_TRANSFORMER_MAX_COMPLETION_TOKENS": env.get(
                "DENSN_TRANSFORMER_MAX_COMPLETION_TOKENS",
                "500",
            ),
            "DENSN_TRANSFORMER_MAX_RULES": env.get("DENSN_TRANSFORMER_MAX_RULES", "4"),
            "DENSN_TRANSFORMER_MAX_FAILING_TESTS": env.get(
                "DENSN_TRANSFORMER_MAX_FAILING_TESTS",
                "1",
            ),
            "DENSN_TRANSFORMER_MAX_COUNTEREXAMPLES": env.get(
                "DENSN_TRANSFORMER_MAX_COUNTEREXAMPLES",
                "1",
            ),
            "DENSN_TRANSFORMER_MAX_LOGS": env.get("DENSN_TRANSFORMER_MAX_LOGS", "1"),
            "DENSN_TRANSFORMER_MAX_SOURCE_VARIABLES": env.get(
                "DENSN_TRANSFORMER_MAX_SOURCE_VARIABLES",
                "8",
            ),
            "DENSN_TRANSFORMER_SOURCE_TEXT_CHARS": env.get(
                "DENSN_TRANSFORMER_SOURCE_TEXT_CHARS",
                "1000",
            ),
            "DENSN_TRANSFORMER_MAX_BACKFILL_REQUESTS": env.get(
                "DENSN_TRANSFORMER_MAX_BACKFILL_REQUESTS",
                "1",
            ),
            "DENSN_GROQ_MODEL_CANDIDATES": env.get(
                "DENSN_GROQ_MODEL_CANDIDATES",
                (
                    "openai/gpt-oss-120b,"
                    "meta-llama/llama-4-scout-17b-16e-instruct,"
                    "llama-3.3-70b-versatile,"
                    "llama-3.1-8b-instant,"
                    "groq/compound-mini"
                ),
            ),
            "DENSN_STAGE_TRACE_PATH": str(_stage_trace_path(stage_name)),
            "DENSN_TRANSFORMER_REQUEST_TRACE_PATH": str(request_trace_path),
            "DENSN_COMMANDS_USED_JSON": env.get("DENSN_COMMANDS_USED_JSON", command_manifest),
        }
    )
    return env


def _read_stage_trace(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _read_json(path)
    except Exception:
        return None


def _run_command(stage: dict[str, Any]) -> dict[str, Any]:
    command = list(stage["command"])
    timeout_seconds = float(stage["timeout_seconds"])
    stage_name = str(stage["name"])
    stage_trace_path = _stage_trace_path(stage_name)
    request_trace_path = OUTPUT_DIR / f"{stage_name}_request_trace.jsonl"
    if stage_trace_path.exists():
        stage_trace_path.unlink()
    if request_trace_path.exists():
        request_trace_path.unlink()
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_live_stage_env(stage_name),
        )
        elapsed = time.perf_counter() - start
        return {
            "stage": stage_name,
            "command": command,
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "ok": completed.returncode == 0,
            "timeout": False,
            "timeout_seconds": timeout_seconds,
            "stage_trace_path": str(stage_trace_path),
            "stage_trace": _read_stage_trace(stage_trace_path),
            "request_trace_path": str(request_trace_path),
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return {
            "stage": stage_name,
            "command": command,
            "returncode": None,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": str(stdout)[-4000:],
            "stderr": str(stderr)[-4000:],
            "ok": False,
            "timeout": True,
            "timeout_seconds": timeout_seconds,
            "stage_trace_path": str(stage_trace_path),
            "stage_trace": _read_stage_trace(stage_trace_path),
            "request_trace_path": str(request_trace_path),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    version = artifact_version_info("phase12", root=ROOT)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "artifact_version": version,
        "completed": False,
        "fresh_bundle_ready": False,
        "stages": [],
        "blocker": None,
        "output_artifacts": {},
        "resumed": bool(args.resume),
    }

    if args.resume and MANIFEST_PATH.exists():
        prior = _read_json(MANIFEST_PATH)
        if prior.get("artifact_version", {}).get("git_sha") == version.get("git_sha"):
            summary["stages"] = list(prior.get("stages", []))

    completed_stage_names = {
        str(stage.get("stage")) for stage in summary["stages"] if stage.get("ok") is True
    }

    for stage in STAGES:
        if args.resume and stage["name"] in completed_stage_names:
            continue
        result = _run_command(stage)
        summary["stages"].append(result)
        _write_json(MANIFEST_PATH, summary, version=version)
        if not result["ok"]:
            summary["blocker"] = _classify_blocker(result)
            _write_json(MANIFEST_PATH, summary, version=version)
            write_text_artifact(
                ROOT / "reports" / "phase12_fresh_live_report.md",
                _report_markdown(summary),
                version=version,
            )
            print(json.dumps(summary, indent=2))
            return

    gauntlet = _read_json(ROOT / "artifacts" / "phase7" / "gauntlet_summary.json")
    if bool(gauntlet.get("republication", {}).get("reused_existing_rows")):
        summary["blocker"] = {
            "kind": "reused_existing_rows_present",
            "reason": "The fresh gauntlet still reports reused rows, so the fresh live canonical bundle is not valid.",
            "command": [sys.executable, "scripts/run_gauntlet.py"],
        }
        _write_json(MANIFEST_PATH, summary, version=version)
        write_text_artifact(
            ROOT / "reports" / "phase12_fresh_live_report.md",
            _report_markdown(summary),
            version=version,
        )
        print(json.dumps(summary, indent=2))
        return

    final_bundle = _read_json(ROOT / "artifacts" / "phase11" / "final_proof_bundle.json")
    _write_json(GAUNTLET_ALIAS_PATH, gauntlet, version=version)
    _write_json(FINAL_BUNDLE_ALIAS_PATH, final_bundle, version=version)

    summary["completed"] = True
    summary["fresh_bundle_ready"] = True
    summary["output_artifacts"] = {
        "fresh_live_gauntlet_summary": str(GAUNTLET_ALIAS_PATH),
        "fresh_live_final_proof_bundle": str(FINAL_BUNDLE_ALIAS_PATH),
        "proposal_precision_summary": str(
            ROOT / "artifacts" / "phase13" / "proposal_precision_summary.json"
        ),
    }
    _write_json(MANIFEST_PATH, summary, version=version)
    write_text_artifact(
        ROOT / "reports" / "phase12_fresh_live_report.md",
        _report_markdown(summary),
        version=version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
