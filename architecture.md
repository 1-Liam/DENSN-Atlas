# Architecture

## Mission

Build a persistent contradiction-driven intelligence system whose defining behavior is:

1. accumulate contradiction across episodes in a long-lived graph,
2. detect when the current ontology is insufficient,
3. synthesize a new reusable abstraction,
4. verify that abstraction externally, and
5. improve performance on related held-out tasks.

This is a research system, not a chatbot.

## North Star

The core capability is verified abstraction invention. The system is successful only when a newly created symbol or invariant:

- emerges because repeated contradictions persist,
- is admitted by the DENSN structural core rather than by language confidence,
- survives external verification,
- improves held-out behavior, and
- is reused later.

## System Shape

The architecture is explicitly two-time-scale.

### Fast system: transformer-facing orchestration

Responsibilities:

- parse natural language, logs, traces, code, and formal artifacts into candidate atoms
- propose candidate constraints, hidden variables, labels, tests, and search queries
- generate repair attempts and verifier calls
- retrieve supporting evidence when abstractions remain semantically thin

This layer is proposal-oriented, not authoritative.

### Slow system: DENSN structural core

Responsibilities:

- maintain the persistent ontology and contradiction memory
- compute truth assignments over the Boolean symbolic core
- track weighted contradiction through the Hamiltonian
- escalate persistent unresolved conflicts
- run spectral diffusion and discrete collapse
- trigger topological structure learning
- synthesize and admit meta-symbols
- decide whether semantic labels are grounded

This layer is authoritative over structure.

## Architectural Laws

### 1. Persistence is mandatory

The graph is not prompt-local. The system maintains one persistent ontology across tasks and episodes.

Every symbol, constraint, observation, and abstraction must retain:

- provenance
- timestamps
- support count
- failure history
- verifier history
- lineage

Repeated contradictions must accumulate history instead of resetting.

### 2. Structure and semantics remain separate

Structural realization and semantic naming are different objects.

- `f_meta`: the learned structural interface function
- `L_meta`: the proposed human-readable label

The transformer may propose `L_meta`, but DENSN only treats it as provisional until:

- the bridge audit passes, and
- external verification supports the symbol's utility

Rejected labels do not erase structural discoveries.

### 3. Symbols must pay rent

New abstractions are expensive. A symbol is admitted only if it:

- reduces contradiction on held-out cases
- improves verifier pass rate, search cost, or sample efficiency
- replays successfully on related tasks
- clears a complexity penalty
- is not a rename of an existing cluster

The ontology is optimized for useful structure, not maximum vocabulary.

## Core Runtime Components

## 1. Graph kernel

The canonical state is a typed persistent bipartite graph `G = (S, C, E)`.

Node families:

- `AtomicSymbol`
- `Constraint`
- `Observation`
- `MetaSymbol`
- `Evidence`
- `Task`
- `VerifierArtifact`

Edge families:

- `participates_in`
- `supports`
- `contradicts`
- `implies`
- `xor`
- `temporal_precedes`
- `provenance_of`
- `abstracts`

The graph is split logically into:

- symbol nodes
- constraint nodes
- typed metadata / evidence nodes

The DENSN Hamiltonian is defined on the symbol-constraint substrate, while evidence, tasks, and verifier artifacts enrich admission decisions and provenance.

## 2. Constraint engine

The first implementation is intentionally deterministic and inspectable.

Properties:

- Boolean truth assignments only in the core solver
- uncertainty stored separately from truth value
- deterministic evaluation for each constraint type
- quarantine layer for transformer-proposed constraints

Constraint types in v1:

- implication
- xor
- equality / equivalence
- mutual exclusion
- temporal precedence
- observation lock / sensory boundary

## 3. Conflict cache

The conflict cache is a first-class memory system.

Responsibilities:

- cache constraint evaluations
- track consecutive violation persistence
- escalate weights monotonically
- saturate at a configured maximum
- compute hotspot scores over subgraphs
- expose contradiction recurrence over time

This is the mechanism that converts chronic contradiction into topological pressure.

## 4. Spectral-MCM dynamics

The inference engine has two inspectable phases.

### Continuous phase

- build weighted incidence matrix `A`
- compute weight matrix `W`
- construct Laplacian `L = A^T W A`
- estimate `lambda_max`
- set stable `kappa < 2 / lambda_max`
- run diffusion over local potentials

### Discrete phase

- compute greedy `DeltaPsi` flips
- inject bounded noise
- support random restart
- support weak-constraint pruning
- support local reweighting

These phases are deliberately separate so the system never collapses into an opaque heuristic search loop.

## 5. Topological Structure Learning

TSL is the system's defining structural adaptation mechanism.

### Pathway A: coherence consolidation

Trigger:

- low residual tension
- plateauing `Psi`

Action:

- compress coherent low-conflict modules
- optimize parsimony and reuse

### Pathway B: frustration-driven abstraction

Trigger:

- high residual tension
- plateauing `Psi`
- repeated hotspot recurrence

Action:

- isolate hotspot by tension density
- compute Markov blanket
- synthesize interface function `f_meta`
- replace or wrap the hotspot with a reusable abstraction
- locally reset and re-equilibrate the affected region

The system must store both the pre-abstraction cluster and the post-abstraction lineage.

## 6. Interface synthesis

Interface synthesis is the bridge between a contradictory cluster and a reusable symbol.

Modes:

- exact logic minimization for small blankets
- approximate interface model for large blankets

The exact mode is preferred whenever tractable because it provides stronger interpretability and cleaner replay behavior.

## 7. Semantic bridge

The semantic bridge is not a naming flourish. It is a structural audit.

Process:

1. the transformer proposes a label, definition, tests, or search query
2. DENSN injects a verification bridge between `L_meta` and `f_meta`
3. the system measures `DeltaPsi`
4. labels above threshold are rejected

The structural abstraction may still be retained anonymously if it is useful.

## 8. Verifier bus

Every important claim should be testable outside the model.

The verifier bus standardizes interaction with:

- theorem provers
- model checkers
- test runners
- interpreters / compilers
- static analyzers
- domain-specific validators

The current research system now supports out-of-process verifier execution as well as in-process Python verifiers, so formal-task claims can be checked against real artifact bundles rather than benchmark-local callbacks.

## 9. Candidate lifecycle evaluation

Admission should not be benchmark-owned. The core must provide a reusable lifecycle path that can:

- evaluate a candidate on train verification,
- replay it on held-out related tasks,
- compare reuse against no-TSL baselines,
- record verification and reuse outcomes in the ontology registry, and
- feed the same admission gate regardless of where the candidate came from.

## 10. Artifact-backed formal tasks

The flagship formal path should consume heterogeneous task bundles rather than hand-authored benchmark tuples. A formal task bundle may include:

- natural-language specifications
- formal rules
- execution traces
- failing tests
- logs
- counterexamples
- source code

These artifacts should be attached to the graph as first-class evidence with provenance edges into the symbolic substrate.

Verifier feedback becomes graph evidence and can create locked observations or high-weight constraints.

## 9. Memory and ontology registry

The registry stores the living ontology.

For each accepted symbol, retain:

- source cluster
- interface logic
- admission metrics
- accepted / rejected labels
- supporting evidence
- verifier outcomes
- task reuse history
- retirement status

Rejected abstractions are also stored to prevent rediscovery loops.

## Phase Order

Implementation must follow this order:

1. design docs
2. Phase 0 reproducibility and telemetry
3. minimal faithful hybrid core
4. transformer integration behind stable interfaces
5. learning and adaptive compute

The project should not jump to deep coupling before the external hybrid proves itself.

## First Domain

Version 1 targets formal systems because claims are externally checkable.

Primary input artifacts:

- natural-language specs
- formal specs
- execution traces
- failing tests
- logs
- counterexamples
- source code

Primary output artifacts:

- missing invariants
- hidden protocol states
- safety guards
- repaired abstractions

## Data Flow

The runtime loop is:

1. ingest artifacts into evidence and candidate symbolic structure
2. quarantine uncertain proposals
3. update the persistent graph
4. run DENSN inference and contradiction telemetry
5. escalate repeated unresolved contradictions
6. trigger TSL when thresholds and recurrence criteria are met
7. synthesize structural abstractions
8. propose semantics and audits
9. call external verifiers
10. admit or reject symbols
11. replay on held-out related tasks
12. persist all outcomes

## Success Criteria

Version 1 is done only if:

1. the faithful DENSN core runs with persistent memory
2. the XOR / TSL escalation pattern is reproduced
3. the system invents at least one nontrivial invariant or hidden state
4. an external verifier confirms it
5. the invention is reused on held-out related tasks
6. the gain disappears in ablations without TSL or conflict memory

## Design Priorities

When tradeoffs appear, choose in this order:

1. verified abstraction invention
2. persistent memory
3. faithful DENSN mechanics
4. benchmark rigor
5. efficiency
6. polish
