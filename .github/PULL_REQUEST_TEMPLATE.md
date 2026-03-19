## Summary

Describe the change in one short paragraph.

## Why This Change Is Needed

- What problem does it fix?
- Why is it safe relative to the frozen-core release?

## Scope

Mark all that apply:

- [ ] docs only
- [ ] packaging / provenance
- [ ] reproducibility fix
- [ ] verifier fix
- [ ] benchmark fix
- [ ] structural core change

## Evidence

If this change affects claims, list:

- raw artifact paths:
- commands run:
- before/after metrics:

## Frozen-Core Check

- [ ] I did not change the structural core
- [ ] If I changed the structural core, it is only to fix a correctness or proof-invalidating bug and I explained why above

## Safety Checks

- [ ] No secrets or local `.env` values were committed
- [ ] No benchmark-local helper logic is being presented as system capability
- [ ] Markdown claims remain aligned with raw JSON artifacts
