# DENSN Atlas

DENSN Atlas is a frozen DENSN proof repository for verifier-backed abstraction invention, transfer, and compression in small formal protocol and concurrency problems.

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

## Supported Claim

The strongest claim this repository is designed to support is:

Given a small formal system with explicit verifier surfaces, DENSN can accumulate persistent contradiction in a long-lived ontology, synthesize a reusable abstraction that resolves the contradiction, verify it externally, and transfer it to related tasks while blocking bad transfer.

In this repository, "formal system" means protocol, distributed-systems, lock/lease, or similar concurrency-oriented artifact bundles with objective external checks.

## What This Repo Does Not Claim

- It does not prove general intelligence.
- It does not prove performance on arbitrary formal systems or arbitrary theorem proving.
- It does not prove scalability to large ontologies or production-scale symbolic state spaces.
- It does not claim broad robustness across many competing verifier ecosystems.
- It does not show that the live model is authoritative over ontology change.

## Current Evidence Envelope

- The proof bundle is strongest on small protocol and concurrency families.
- The canonical internal proof focuses on verifier-backed abstraction invention, transfer, negative-transfer blocking, and Pathway A compression.
- The external real-world lane currently covers a small number of upstream artifact bundles rather than a broad benchmark suite.
- The repo is intended as a rigorous `0.1.x` research release, not a finished platform.

## Canonical Raw Artifacts

- [artifacts/phase10/proof_manifest.json](artifacts/phase10/proof_manifest.json): provenance and command manifest for the canonical proof line
- [artifacts/phase11/final_proof_bundle.json](artifacts/phase11/final_proof_bundle.json): canonical proof payload
- [artifacts/phase12/fresh_live_run_manifest.json](artifacts/phase12/fresh_live_run_manifest.json): source of truth for the fresh-live rerun chain and completion state
- [artifacts/phase12/fresh_live_final_proof_bundle.json](artifacts/phase12/fresh_live_final_proof_bundle.json): fresh-live alias of the canonical proof payload when the rerun re-materializes the same end state
- [artifacts/phase12/README.md](artifacts/phase12/README.md): explains the relationship between the fresh-live manifest and the fresh-live bundle alias
- [artifacts/readiness/release_audit.json](artifacts/readiness/release_audit.json): release gate and reproducibility checks

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
- [CHANGELOG.md](CHANGELOG.md): public release history
- [CITATION.cff](CITATION.cff): citation metadata for the repository
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution rules for the frozen release line
- [CODEOWNERS](CODEOWNERS): default ownership for public review
- [SECURITY.md](SECURITY.md): security and credential-reporting policy
- [SUPPORT.md](SUPPORT.md): issue scope and support expectations
- [repro/README.md](repro/README.md): reproduction workflow
- [wedge/README.md](wedge/README.md): narrow formal-systems wedge
- [DENSN_FRAMEWORK_EXPERT_BRIEF.md](DENSN_FRAMEWORK_EXPERT_BRIEF.md): manuscript-oriented framework brief
- [COMMERCIAL-LICENSING.md](COMMERCIAL-LICENSING.md): commercial use policy

## Licensing

This repository is released under [PolyForm Strict 1.0.0](LICENSE.txt).

That means the code is public for inspection and permitted noncommercial use under the license terms, but it is not an open-source license in the OSI sense, and commercial rights are reserved.

## Evidence Rule

When a Markdown statement disagrees with raw JSON, trust the raw JSON.
