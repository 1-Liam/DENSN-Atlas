# DENSN Atlas

DENSN Atlas is a frozen DENSN proof repository for verifier-backed abstraction invention, transfer, and compression.

This repository is intentionally release-oriented:

- the structural core is frozen
- raw JSON artifacts are the source of truth
- Markdown is limited to operator docs, contracts, and reproduction guidance
- proposal generation is quarantined and never mutates ontology directly

## What This Repo Shows

- DENSN invents verifier-backed abstractions under persistent contradiction.
- Pathway B is the main invention mechanism: persistent high-tension hotspots trigger TSL, isolate a contradiction cluster, compute its Markov blanket, and synthesize a new reusable abstraction.
- Those abstractions remap across different formal families when the interface supports it.
- Pathway B is active in the flagship proof runs, the fresh-live bundle, and the external real-world solves; accepted `tsl_event` telemetry is the direct evidence.
- Pathway A compression reduces future solve cost in a low-conflict regime.
- Bad transfer and cross-family misuse are blocked under verifier scrutiny.
- A quarantined live model helps proposals without gaining ontology authority.

## Canonical Raw Artifacts

- [artifacts/phase10/proof_manifest.json](artifacts/phase10/proof_manifest.json)
- [artifacts/phase11/final_proof_bundle.json](artifacts/phase11/final_proof_bundle.json)
- [artifacts/phase12/fresh_live_final_proof_bundle.json](artifacts/phase12/fresh_live_final_proof_bundle.json)
- [artifacts/phase12/fresh_live_run_manifest.json](artifacts/phase12/fresh_live_run_manifest.json)
- [artifacts/readiness/release_audit.json](artifacts/readiness/release_audit.json)

## Setup

1. Install Python `3.12+`.
2. Create your local environment file from the template:

```powershell
Copy-Item .env.example .env
```

3. Add your own Groq key to `.env`, or set it directly in your shell:

```powershell
$env:GROQ_API_KEY="your_key_here"
```

Notes:

- No API keys are shipped in this repository.
- `.env` is gitignored and should never be committed.
- Live proposal-path scripts require `GROQ_API_KEY`.
- Core proof artifacts and many offline checks do not require a live model key.

## Quick Start

Reproduce the canonical bundle:

```powershell
./repro/run_repro.ps1
```

Run the fresh-live chain:

```powershell
python scripts/run_fresh_live_bundle.py
```

Run the decisive wedge demo:

```powershell
python scripts/run_decisive_demo.py
python scripts/run_wedge_eval.py
```

Run the release audit:

```powershell
python scripts/run_release_audit.py
```

## Repo Map

- [architecture.md](architecture.md): frozen system shape and laws
- [interfaces.md](interfaces.md): stable module and contract boundaries
- [evaluation_contract.md](evaluation_contract.md): evidence hierarchy and claim rules
- [failure_modes.md](failure_modes.md): operational risks and mitigations
- [repro/README.md](repro/README.md): reproduction workflow
- [wedge/README.md](wedge/README.md): narrow formal-systems wedge
- [DENSN_FRAMEWORK_EXPERT_BRIEF.md](DENSN_FRAMEWORK_EXPERT_BRIEF.md): manuscript-oriented framework brief
- [COMMERCIAL-LICENSING.md](COMMERCIAL-LICENSING.md): commercial use policy

## Licensing

This repository is released under [PolyForm Strict 1.0.0](LICENSE.txt).

That means the code is public for inspection and permitted noncommercial use under the license terms, but it is not an open-source license in the OSI sense, and commercial rights are reserved.

## Evidence Rule

When a Markdown statement disagrees with raw JSON, trust the raw JSON.
