# Consumer Conformance Runner Implementation Plan

> **For agentic workers:** Execute inline with TDD and fresh verification after
> each task; subagent delegation is intentionally unavailable for this goal.

**Goal:** Add a versioned consumer conformance adapter schema and a
test-framework-neutral TypeScript factory runner, validate one VMx fixture, and
pilot one DayDreams VM without code generation.

**Architecture:** A strict language-neutral JSON Schema defines ordered invoke,
state assertion, and message assertion steps. A separately bundled TypeScript
entry validates suites, executes consumer-provided adapters sequentially, and
owns deterministic teardown. Product YAML and domain fixtures remain
consumer-owned inputs adapted at the boundary.

**Tech stack:** JSON Schema 2020-12, TypeScript, Ajv, tsup, Vitest, MkDocs
three-surface documentation.

## Global constraints

- The schema is a non-normative adapter contract, not a VMx viewmodel dialect.
- Do not parse YAML or add Swift/code generation.
- Do not replace or weaken any five-flavor conformance test.
- Keep the conformance entry out of the root runtime bundle.
- Await operations in declaration order and dispose every created adapter once.
- TypeScript becomes 3.21.0 while its minimum/current spec remains 3.20.0.

## Task 1: Schema and validation red/green

- [ ] Add failing tests for valid v1, unsupported version, malformed steps,
  unknown fields, and actionable Ajv instance paths.
- [ ] Run the focused test and confirm import/schema failures.
- [ ] Add the canonical JSON Schema, schema sync, JSON/TypeScript types,
  validation error, and `parseConsumerConformance`.
- [ ] Run focused tests, typechecks, lint, and commit.

## Task 2: Runner ordering, diagnostics, and teardown red/green

- [ ] Add failing tests for sync/async invoke ordering, JSON Pointer state,
  exact message order, factory failure, operation failure, mismatch paths,
  teardown on success/failure, and teardown-error preservation.
- [ ] Implement structural JSON equality, pointer resolution, case execution,
  whole-suite reporting, and typed execution errors.
- [ ] Run focused/full TypeScript tests and commit.

## Task 3: Existing VMx fixture adapter and package surface

- [ ] Add a failing CMD truth-table adapter test that executes every unchanged
  row through the generic runner.
- [ ] Implement `adaptCommandTruthTableFixture` and a test factory using real
  `RelayCommand` behavior; keep CMD-007 unchanged.
- [ ] Add the conformance tsup/package export, Ajv dependency, schema sync,
  ESM/CJS/declaration/pack smoke coverage, and TypeScript 3.21.0 metadata.
- [ ] Run clean install, sync, typechecks, lint, build, tests, audit, and pack.

## Task 4: ADR, gap table, and three-surface docs

- [ ] Add ADR-0102 deciding the adapter-schema status and Swift/codegen gate.
- [ ] Publish the full VMx/DayDreams field gap table, schema semantics, factory
  API, errors, teardown, examples, and non-goals in canonical docs.
- [ ] Update ADR counts, TypeScript README/changelog, root status, compatibility
  matrix, spec schema index, and generated site/wiki.
- [ ] Run strict docs, link, tooling, version, fixture, and conformance checks.

## Task 5: DayDreams no-push pilot

- [ ] Pack VMx 3.21.0 and install it only in the disposable DayDreams clone.
- [ ] Adapt AppVM's two fixture cases and replace its bespoke loop with factory
  registration while leaving non-fixture tests intact.
- [ ] Run AppVM/viewmodel tests and typecheck; measure net harness LOC and record
  exact evidence in a tracked pilot report.
- [ ] Delete the clone after capturing evidence; never push it.

## Task 6: Final verification and git flow

- [ ] Audit every acceptance criterion and the complete diff for scope, secrets,
  compatibility, ordering, failure handling, and cleanup leaks.
- [ ] Run all applicable TypeScript, docs, tooling, version, fixture,
  five-flavor coverage, pre-commit, and diff gates.
- [ ] Merge a green ticket-only PR to develop, then a green develop-to-main PR.
- [ ] Verify post-main workflows and live docs/wiki, finalize #95, clean the
  worktree/branch, and begin #58.
