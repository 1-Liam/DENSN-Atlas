# Interfaces

## Purpose

This document defines stable interfaces between the persistent DENSN core, transformer-facing proposal layers, and external verifiers. The goal is to keep the architecture inspectable and swappable.

## Design Rules

- The DENSN core owns ontology mutation.
- Transformer components may propose but may not directly admit symbols.
- Every interface must preserve provenance and timestamps.
- Every accepted structural change must be replayable from logs.

## Project Modules

- `densn.artifacts`
- `densn.graph`
- `densn.constraints`
- `densn.cache`
- `densn.dynamics`
- `densn.tsl`
- `densn.semantic`
- `densn.verifier`
- `densn.memory`
- `densn.lifecycle`
- `densn.benchmarks`
- `densn.telemetry`
- `densn.transformer`

## Artifact Ingestion

### `attach_artifact_manifest`

Contract:

- input: graph plus manifest path for a formal task bundle
- output: task node, evidence nodes, and provenance edges attached to the graph

The ingestor should preserve artifact references for:

- natural-language specs
- formal specs
- execution traces
- failing tests
- logs
- counterexamples
- source code paths

## Core Types

The initial implementation should use explicit dataclasses and typed dictionaries so artifacts are easy to inspect and serialize.

## Node Types

### AtomicSymbol

Fields:

- `id`
- `name`
- `truth_value`
- `locked`
- `created_at`
- `updated_at`
- `support_count`
- `failure_count`
- `provenance_ids`
- `task_ids`
- `metadata`

### Constraint

Fields:

- `id`
- `kind`
- `symbol_ids`
- `weight`
- `base_weight`
- `max_weight`
- `locked`
- `created_at`
- `updated_at`
- `support_count`
- `failure_count`
- `persistence`
- `provenance_ids`
- `evaluator_key`
- `metadata`

### Observation

Fields:

- `id`
- `symbol_id`
- `observed_value`
- `locked`
- `source`
- `created_at`
- `provenance_ids`
- `metadata`

### MetaSymbol

Fields:

- `id`
- `structural_name`
- `semantic_label`
- `semantic_status`
- `interface_kind`
- `interface_inputs`
- `interface_definition`
- `parent_cluster_symbol_ids`
- `markov_blanket_symbol_ids`
- `admission_status`
- `admission_metrics`
- `created_at`
- `updated_at`
- `provenance_ids`
- `metadata`

### Evidence

Fields:

- `id`
- `kind`
- `content_ref`
- `source`
- `created_at`
- `task_id`
- `metadata`

### Task

Fields:

- `id`
- `family`
- `split`
- `description`
- `created_at`
- `metadata`

### VerifierArtifact

Fields:

- `id`
- `verifier_name`
- `artifact_kind`
- `status`
- `cost`
- `counterexample_ref`
- `created_at`
- `metadata`

## Edge Types

Each edge should at least include:

- `id`
- `src_id`
- `dst_id`
- `kind`
- `created_at`
- `provenance_ids`
- `metadata`

Supported kinds in v1:

- `participates_in`
- `supports`
- `contradicts`
- `implies`
- `xor`
- `temporal_precedes`
- `provenance_of`
- `abstracts`

## Graph API

### `PersistentGraph`

Required methods:

- `add_node(node) -> str`
- `add_edge(edge) -> str`
- `get_node(node_id) -> Node`
- `get_edge(edge_id) -> Edge`
- `iter_nodes(kind=None) -> Iterable[Node]`
- `iter_edges(kind=None) -> Iterable[Edge]`
- `neighbors(node_id, edge_kind=None) -> list[str]`
- `subgraph(node_ids) -> PersistentGraph`
- `snapshot() -> GraphSnapshot`
- `save(path) -> None`
- `load(path) -> PersistentGraph`

Required properties:

- persistent storage path
- graph version
- created_at
- updated_at

## Constraint Interface

### `ConstraintEvaluator`

Contract:

- input: constraint record plus current Boolean assignment map
- output: evaluation result with violation flag and local details

Suggested API:

`evaluate(constraint, assignment) -> ConstraintEvaluation`

`ConstraintEvaluation` fields:

- `constraint_id`
- `violated`
- `satisfied`
- `delta_if_flipped`
- `details`

### `ConstraintEngine`

Required methods:

- `register(kind, evaluator) -> None`
- `evaluate_constraint(constraint_id, assignment) -> ConstraintEvaluation`
- `evaluate_all(graph, assignment) -> list[ConstraintEvaluation]`
- `compute_hamiltonian(graph, assignment) -> float`
- `compute_local_potentials(graph, assignment) -> dict[str, float]`
- `compute_forcing_vector(graph, assignment) -> dict[str, float]`

## Conflict Cache Interface

### `ConflictCache`

Required methods:

- `record(evaluation_batch) -> None`
- `get_persistence(constraint_id) -> int`
- `get_weight(constraint_id) -> float`
- `escalate(constraint_id) -> float`
- `reset_local(constraint_ids) -> None`
- `rank_hotspots(graph) -> list[HotspotScore]`
- `stats() -> ConflictCacheStats`

`HotspotScore` fields:

- `cluster_id`
- `constraint_ids`
- `symbol_ids`
- `tension`
- `persistence_mass`
- `rank_score`

## Dynamics Interface

### `SpectralDynamics`

Required methods:

- `build_incidence_matrix(graph) -> MatrixBundle`
- `build_laplacian(graph) -> MatrixBundle`
- `estimate_lambda_max(laplacian) -> float`
- `initialize_kappa(lambda_max) -> float`
- `diffuse(phi, laplacian, forcing, kappa) -> DiffusionStep`
- `quadratic_energy(phi, laplacian) -> float`

### `CollapseEngine`

Required methods:

- `score_flips(graph, assignment, phi) -> list[FlipCandidate]`
- `apply_greedy_step(graph, assignment, candidates) -> CollapseStep`
- `apply_noisy_step(graph, assignment, candidates, noise_probability) -> CollapseStep`
- `run_cycle(graph, assignment, phi) -> CollapseCycle`

## TSL Interface

### `TSLEngine`

Required methods:

- `should_trigger_pathway_a(metrics) -> bool`
- `should_trigger_pathway_b(metrics) -> bool`
- `find_clusters(graph, hotspot_scores, mode) -> list[ClusterCandidate]`
- `compute_markov_blanket(graph, cluster_symbol_ids) -> list[str]`
- `synthesize_interface(cluster, blanket, mode) -> InterfaceSynthesisResult`
- `propose_meta_symbol(cluster, blanket, interface_result) -> MetaSymbolProposal`
- `apply_abstraction(graph, proposal) -> TopologyRevision`
- `local_reset(graph, revision) -> None`

## Semantic Interface

### `SemanticBridge`

Required methods:

- `propose_labels(meta_symbol, context) -> list[LabelProposal]`
- `bridge_constraint(meta_symbol, label) -> Constraint`
- `measure_delta_psi(graph, assignment, bridge_constraint) -> float`
- `audit(meta_symbol, label, graph, assignment) -> SemanticAuditResult`

`SemanticAuditResult` fields:

- `label`
- `delta_psi`
- `accepted`
- `reason`

## Verifier Interface

### `VerifierBus`

Canonical entrypoint:

`verify(claim) -> VerificationResult`

`claim` may be:

- invariant
- hidden-state model
- code patch
- repair candidate
- proof obligation

`VerificationResult` fields:

- `status`
- `pass`
- `fail`
- `counterexample`
- `cost`
- `artifact_ids`
- `verifier_name`
- `details`

Required behavior:

- failed verification produces evidence
- counterexamples are reinserted into the graph
- passing results increase support for the associated abstraction

## Memory Registry Interface

### `OntologyRegistry`

Required methods:

- `record_candidate(meta_symbol) -> None`
- `record_semantic_audit(meta_symbol_id, audit_result) -> None`
- `record_verification(meta_symbol_id, verification_result) -> None`
- `record_reuse(meta_symbol_id, task_id, outcome) -> None`
- `admit(meta_symbol_id, reason) -> None`
- `reject(meta_symbol_id, reason) -> None`
- `retire(meta_symbol_id, reason) -> None`
- `summary() -> RegistrySummary`

## Transformer Adapter Interface

### `TransformerAdapter`

Required methods:

- `extract_atoms(artifacts) -> ProposalBatch`
- `extract_constraints(artifacts) -> ProposalBatch`
- `propose_hidden_variables(context) -> ProposalBatch`
- `propose_labels(meta_symbol, context) -> ProposalBatch`
- `generate_tests(claim, context) -> ProposalBatch`
- `retrieve_evidence(query) -> ProposalBatch`

All outputs are proposals. None directly mutate the persistent graph.

## Benchmark Interface

### `BenchmarkTask`

Required fields:

- `task_id`
- `family`
- `split`
- `inputs`
- `expected_verifier_behavior`
- `metadata`

### `BenchmarkRunner`

Required methods:

- `run_task(task, system) -> TaskResult`
- `run_suite(tasks, system) -> SuiteResult`
- `compare(result_a, result_b) -> ComparisonReport`

## Telemetry Interface

### `TelemetryRecorder`

Required metrics in Phase 0:

- `psi`
- `dpsi_dt`
- `q`
- `hotspot_scores`
- `persistence_counters`
- `accepted_symbols`
- `rejected_symbols`
- `verifier_outcomes`
- `graph_size`
- `runtime`

Required methods:

- `record_step(event) -> None`
- `record_metric(name, value, step=None) -> None`
- `flush(path) -> None`
- `summary() -> dict`

## Persistence Format

Initial persistence format:

- JSON for logs and registry records
- JSONL for telemetry streams
- optional pickle-free matrix export in NumPy-compatible formats

The first version should bias toward inspectable text artifacts over compact opaque storage.
