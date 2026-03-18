# DENSN Repro Kit

## Goal

Reproduce the current canonical DENSN proof bundle without modifying the frozen core.

## Prerequisites

- Python available on `PATH`
- `.env.example` copied to `.env`, or `GROQ_API_KEY` set in your shell for live proposal-path scripts
- Repo checked out at the expected revision or a compatible descendant

## Environment Setup

```powershell
Copy-Item .env.example .env
```

Then set your own Groq key in `.env` or in the shell:

```powershell
$env:GROQ_API_KEY="your_key_here"
```

## One-Command Repro

```powershell
./repro/run_repro.ps1
```

For a full fresh live attempt instead of the current canonical chain:

```powershell
./repro/run_repro.ps1 -FreshLive
```

## Verification

The repro run ends by executing `python scripts/verify_repro_run.py`, which compares the current outputs against `repro/expected_metrics.json` and emits `artifacts/phase12/repro_verification_summary.json`.
