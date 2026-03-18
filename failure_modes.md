# Failure Modes

## Purpose

This project should assume failure by default and instrument against it. The main risk is building a system that looks conceptually rich while actually performing shallow relabeling or overfitting.

## Category 1: Fake contradiction

Description:

- noisy extraction or bad constraints create contradictions that are not real

Symptoms:

- rapidly growing `Psi` without coherent hotspot structure
- high verifier disagreement with extracted graph
- repeated TSL on junk clusters

Mitigations:

- deterministic evaluators first
- quarantine transformer proposals
- provenance requirements on every atom and constraint
- high-weight locked observations from verifier counterexamples

## Category 2: Ontology bloat

Description:

- TSL creates symbols that do not improve reuse or verifier outcomes

Symptoms:

- graph size grows faster than contradiction reduction
- many abstractions remain unused
- held-out gains disappear

Mitigations:

- aggressive symbolic tax
- held-out admission requirement
- retirement policy for low-value symbols
- reuse tracking in the ontology registry

## Category 3: Semantic hallucination

Description:

- the transformer proposes persuasive but wrong labels or explanations

Symptoms:

- labels pass human sniff tests but increase `DeltaPsi`
- verifier outcomes disagree with semantic framing

Mitigations:

- semantic bridge audit
- anonymous structural identifiers when semantics fail
- external verification before high-confidence naming

## Category 4: Local repair without abstraction

Description:

- the system solves the spawning case through brute force, restart tricks, or local search, but never invents a reusable symbol

Symptoms:

- search cost remains high across related tasks
- no transfer benefit
- no stable meta-symbol lineage

Mitigations:

- require reuse on held-out tasks
- compare against no-TSL ablations
- log whether improvements come from abstraction or just more compute

## Category 5: Cluster renaming mistaken for invention

Description:

- the system renames a coherent cluster without creating a new useful interface or invariant

Symptoms:

- the interface logic does not add explanatory or predictive power
- abstraction is equivalent to an existing grouping

Mitigations:

- explicit novelty test against existing symbols
- admission criteria requiring verifier or search gains
- lineage checks in the registry

## Category 6: Spectral cost explosion

Description:

- dense Laplacian operations dominate runtime or memory

Symptoms:

- matrix construction becomes the bottleneck
- high runtime for modest graph sizes
- local-only approximations miss important global structure

Mitigations:

- sparse matrices by default
- localized spectral mode with explicit telemetry
- cache reuse for stable subgraphs
- benchmark runtime and memory honestly

## Category 7: Over-escalation and thrashing

Description:

- conflict weights grow too aggressively and destabilize the search

Symptoms:

- repeated oscillation
- excessive random restarts
- Pathway B triggers too often

Mitigations:

- saturation cap
- hotspot thresholding
- local reset after accepted TSL
- rate-limited escalation schedules

## Category 8: Verifier overfitting

Description:

- abstractions are tailored to the specific verifier or benchmark artifact rather than the underlying task family

Symptoms:

- strong gains on the exact benchmark
- weak transfer on sibling tasks
- brittle behavior under alternate verifier settings

Mitigations:

- held-out family evaluation
- multiple verifier artifacts where possible
- replay across related tasks before admission

## Category 9: Persistent memory corruption

Description:

- stale or wrong symbols accumulate and poison future reasoning

Symptoms:

- contradiction grows in unrelated task families
- symbol reuse hurts more than it helps
- provenance and timestamps become inconsistent

Mitigations:

- full lineage tracking
- retirement status
- rejection memory for previously failed symbols
- snapshot and replay tools

## Category 10: Transformer authority creep

Description:

- the transformer begins to effectively control ontology mutation through implicit or unchecked proposals

Symptoms:

- accepted symbols lack structural evidence
- graph mutations occur without DENSN admission paths

Mitigations:

- strict interface boundaries
- quarantine layer for all proposals
- audit logs for every accepted mutation

## Category 11: Missing held-out rigor

Description:

- the system appears to invent abstractions, but those abstractions never prove themselves outside the spawning case

Symptoms:

- impressive local demos
- weak or absent transfer
- missing ablation evidence

Mitigations:

- held-out admission gate
- transfer benchmarks paired with every invention benchmark
- mandatory ablations for conflict cache and TSL

## Category 12: Cosmetic success reporting

Description:

- reports emphasize polished explanations, labels, or demos instead of verifier-backed gains

Symptoms:

- narrative strength exceeds metric strength
- missing failure accounting

Mitigations:

- standardized reports after each phase
- explicit section for cosmetic-only wins
- benchmark-first project governance

## Failure Policy

If a benchmark fails, do not patch over it with longer prompts, larger models, or prettier explanations until logs identify the structural cause. The system should prefer visible failure over hidden drift.
