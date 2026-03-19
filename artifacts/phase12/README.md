# Phase 12 Artifact Notes

`fresh_live_run_manifest.json` is the source of truth for the fresh-live rerun.

It records:

- whether the fresh-live chain completed,
- whether the fresh bundle is ready,
- which stages ran,
- whether any blocker occurred,
- and which output artifacts were produced.

`fresh_live_final_proof_bundle.json` is intentionally an alias of the canonical proof payload when the fresh-live rerun reaches the same end state as the canonical `phase11` bundle.

So if those two proof bundles are byte-identical, that does not mean the fresh-live rerun was skipped. The evidence of the rerun is the successful chain recorded in `fresh_live_run_manifest.json`.
