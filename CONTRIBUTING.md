# Contributing

Thanks for taking DENSN Atlas seriously enough to inspect or improve it.

This repository is not a fast-moving feature branch. It is a public, evidence-first research release with a frozen structural core and a narrow supported claim surface.

## Before You Open A PR

Please read:

- [README.md](README.md)
- [architecture.md](architecture.md)
- [evaluation_contract.md](evaluation_contract.md)
- [repro/README.md](repro/README.md)
- [SUPPORT.md](SUPPORT.md)

## What Kinds Of Changes Are Welcome

- reproducibility fixes
- verifier or benchmark bug fixes
- documentation clarifications that tighten the supported claim
- release-audit fixes
- provenance, packaging, or safety improvements

## What Needs Extra Scrutiny

Changes to any of the following should be treated as high-risk:

- `densn/system.py`
- `densn/tsl.py`
- ontology admission, reuse, retirement, or verifier-integration paths
- canonical proof artifacts
- benchmark logic that could blur system capability vs benchmark-local helper logic

## Frozen-Core Rule

The structural core is frozen for the public release line.

Do not propose core changes unless:

- they fix a correctness bug,
- they fix a proof-invalidating flaw, or
- they repair a reproducibility defect.

If a PR changes the structural core, the burden of proof is high. Explain exactly why the change is necessary and which raw artifacts must be regenerated.

## Evidence Rule

Raw JSON artifacts outrank Markdown summaries.

If your change affects a claim, include:

- the exact command run,
- the raw artifact path,
- the before/after metric difference,
- and why the change does not inflate the public claim.

## What Not To Do

- do not broaden the claim surface beyond the current evidence
- do not add benchmark-local helper logic and present it as system capability
- do not commit credentials or private `.env` files
- do not quietly rewrite canonical artifacts without explaining why
- do not optimize for demo polish at the expense of evidence quality

## Reproducibility Expectation

When possible, validate changes with:

```powershell
python scripts/run_release_audit.py
```

If the change affects the proof surface, also explain whether:

- `artifacts/phase10/proof_manifest.json`
- `artifacts/phase11/final_proof_bundle.json`
- `artifacts/phase12/fresh_live_final_proof_bundle.json`

should or should not change.
