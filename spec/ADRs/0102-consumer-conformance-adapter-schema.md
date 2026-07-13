# ADR 0102 — Consumer conformance adapter schema and TypeScript factory runner

**Status:** Accepted (2026-07-12)
**Spec version:** 3.20.0 (supporting adapter; no normative behavior change)
**Related:** ADR-0006, ADR-0065, ADR-0101, issue #95

## 1. Context

VMx has four purpose-built JSON fixtures and a Markdown conformance catalog.
Consumers may have their own viewmodel descriptions, fixtures, and test
harnesses, but those artifacts do not share a VMx-owned executable dialect.
DayDreams, for example, has YAML viewmodel descriptions, unrelated JSON case
shapes, and hand-written Vitest loops. Calling that YAML an existing VMx format
would make consumer prose and TypeScript type expressions normative by accident.

The useful common boundary is smaller: instantiate consumer state, invoke named
operations in order, assert JSON state and normalized hub messages, and always
tear down the instance. That boundary can be language-neutral without defining
a viewmodel or replacing the normative five-flavor conformance suites.

## 2. Decision

### 2.1 Publish a non-normative adapter schema

`spec/schemas/consumer-conformance-v1.schema.json` is a versioned supporting
artifact. It defines executable suites with opaque JSON fixtures and ordered
`invoke`, `assert-state`, and `assert-messages` steps. It does not define VMx
behavior, consumer domain types, YAML fields, or a viewmodel description.

The adapter schema versions independently through `$schema-version`. A change
that invalidates an accepted suite requires a new schema version. Unknown
structural fields fail validation; JSON data inside fixtures, arguments,
expected state, and normalized message records remains consumer-owned.

### 2.2 Add a test-framework-neutral TypeScript runner

TypeScript 3.21.0 adds `@thekaveh/vmx/conformance`, isolated from the root
runtime entry. A factory receives suite and case fixtures and returns an adapter
with `invoke`, `snapshot`, `drainMessages`, and `dispose` operations. Factory,
invoke, and disposal results may be synchronous or awaitable.

Cases and steps execute in declaration order. State assertions resolve RFC 6901
JSON Pointers and compare structural JSON values. Message assertions drain and
compare an exact ordered record list. Diagnostics retain suite, case, step, and
schema-style instance paths.

After factory success, the runner calls adapter disposal exactly once in a
`finally` path. A disposal failure is reported and never hides an earlier
execution failure. The runner imports no Vitest, Jest, or other test API.

### 2.3 Prove adaptation without replacing normative coverage

`adaptCommandTruthTableFixture` maps every unchanged command truth-table row to
the adapter schema. The existing CMD-007 conformance test remains authoritative
and unchanged, and the five-flavor coverage gate continues to require every
normative ID. This supporting tool adds no conformance ID or spec version bump.

### 2.4 Gate Swift and code generation separately

This decision adds no YAML parser, Swift runner, Swift skeleton, or generator.
A follow-up requires a separate ADR plus all of the following evidence:

1. The adapter contract succeeds in at least two independent consumers.
1. A native Swift factory implements it without TypeScript assumptions.
1. A maintained consumer domain-type mapping shows generation is safer than a
   manual implementation.

## 3. Consequences

- Consumers can reuse one strict operation/assertion runner while retaining
  ownership of their fixtures, types, setup, snapshots, and message encoding.
- TypeScript gains an additive public subpath and Ajv dependency; the root VMx
  entry does not import or re-export either.
- Schema and execution failures become path-addressable, and setup/teardown
  ownership is explicit.
- VMx's normative Markdown, fixtures, conformance IDs, and five-flavor parity
  rules remain unchanged.

## 4. Rejected alternatives

### 4.1 Make DayDreams YAML the VMx viewmodel schema

Rejected. Its fields include product prose and language-specific type strings,
and VMx has no pre-existing YAML dialect to standardize.

### 4.2 Generate tests or Swift source directly from consumer YAML

Rejected. It couples execution to an unreviewed description format and claims
cross-language portability without a second implementation or consumer.

### 4.3 Replace the existing VMx conformance harnesses

Rejected. The generic adapter does not encode the fixture-specific and
language-specific assertions already enforced by the normative suites.
