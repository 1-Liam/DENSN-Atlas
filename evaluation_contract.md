# Evaluation Contract

## Evidence Hierarchy

1. Versioned raw JSON artifacts
2. Canonical raw JSON aliases
3. Generated JSON summaries
4. Generated Markdown
5. Narrative notes

## Required Fields

Every benchmark or proof artifact that supports a claim must expose:

- `artifact_version`
- `proof_contract.core_mode`
- `proof_contract.core_api_version`
- `proof_contract.verifier_stack`
- `proof_contract.proposal_adapter`
- `proof_contract.runtime_metrics`
- `proof_contract.transfer_metrics`
- `proof_contract.lifecycle_metrics`

## Claim Rules

- No invention claim without an accepted verifier-backed symbol in raw artifacts.
- No transfer claim without target-family verifier outcome and contradiction effect.
- No proposal-value claim without unchanged ontology authority and raw runtime metrics.
- No baseline-superiority claim without equal-budget evidence in raw artifacts.
- No Markdown file may introduce facts that do not exist in raw JSON.

## Failure Rules

- Missing raw evidence beats a positive report.
- Contradictory raw artifacts force a `not enough evidence` verdict.
- Any benchmark-local shortcut that bypasses the shared system API invalidates the result.
- Generated reports are convenience surfaces, not the proof surface.
