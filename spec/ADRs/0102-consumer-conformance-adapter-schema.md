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
Case IDs are unique within a suite so reports and diagnostic paths remain
unambiguous.

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

## 5. Appendix: DayDreams discovery evidence

The design discovery for this decision compared the VMx fixtures with the
DayDreams consumer artifacts. These tables record that discovery evidence.

### 5.1 Discovery and gap table

VMx's fixtures, the conformance catalog, and DayDreams' consumer files have
different responsibilities. Adapter v1 standardizes only their executable
boundary.

| Concern           | VMx fixtures/catalog                                              | DayDreams YAML/JSON                                                                                | Adapter v1 decision                                                    |
| ----------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Version           | `$schema-version` on four JSON fixtures                           | YAML `version`; JSON fixtures unversioned                                                          | Require `$schema-version: "1.0.0"` on executable suites                |
| Identity          | Fixture-specific `id`/`name`; catalog headings hold normative IDs | JSON cases hold AVM/GVM/WVM IDs                                                                    | Require a unique stable case `id`; IDs remain consumer-owned           |
| Description       | Free text on some scenarios                                       | YAML and JSON descriptions                                                                         | Optional suite/case descriptions                                       |
| Setup             | Fixture-specific roots such as states, transforms, or scene paths | `initialRoute`, entries/scene fixtures, streaming setup                                            | Opaque JSON suite/case `fixture` values passed to the factory          |
| Operations        | `via`, mutation tuples, producer sends, predicate/task flags      | YAML `operations`; JSON `when.op` with bespoke payloads                                            | Ordered `invoke` steps with a name and JSON argument array             |
| State             | Fixture-specific expected fields                                  | Bespoke `then` keys                                                                                | `assert-state` with RFC 6901 JSON Pointer and structural JSON equality |
| Messages          | Message-ordering arrays and conformance prose                     | Encoded trace strings such as `PropertyChangedMessage:model@appVm`                                 | Exact ordered JSON records consumed by `assert-messages`               |
| Async             | No shared execution shape                                         | No generic async contract                                                                          | Await factory, every `invoke`, and `dispose` before continuing         |
| Errors            | Lifecycle `legal`; test code owns exceptions                      | Bespoke harness branches                                                                           | Validation/execution errors retain suite, case, step, and JSON paths   |
| Teardown          | Each flavor test owns cleanup                                     | Each test calls `dispose()`                                                                        | Runner calls adapter `dispose` exactly once after factory success      |
| YAML model fields | None                                                              | `vm`, `model`, `types`, `children`, `state`, `dependencies`, `derived`, `lifecycle`, `conformance` | Discovery input only; not adapter-schema fields                        |
| Code generation   | None                                                              | Swift generation described as a future goal                                                        | Out of scope                                                           |

### 5.2 Artifact field inventory

The discovery used the following concrete fields. DayDreams fields are pinned
to consumer commit `8d314dd`; they are evidence, not VMx-owned names.

| Artifact                         | Fields observed                                                                                                                                       | Adapter status                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| VMx `command-truthtable.json`    | `$schema-version`; `cases[]` with `id`, `predicate`, `task`, `trigger_emits`, `can_execute`, `execute_invokes_task`, `can_execute_changed_fires`      | Shipped adapter keeps each row as `case.fixture`, invokes `evaluate`, and asserts the three result fields       |
| VMx `derived-properties.json`    | `$schema-version`, `transforms`; `scenarios[]` with `name`, `sources_initial`, `transform`, `mutations`, `expected_values`                            | Could map mutations to `invoke` and values to state assertions; no adapter is shipped in v1                     |
| VMx `lifecycle-transitions.json` | `$schema-version`, `states`, `initial_state`, `terminal_states`, `notes`; `transitions[]` with `from`, `via`, `legal`, `to_intermediate`, `to_final`  | Requires a factory operation per transition and explicit legal/error normalization; no adapter is shipped in v1 |
| VMx `message-ordering.json`      | `$schema-version`; `scenarios[]` with `id`, `description`, producer-send variants, subscriber count, unsubscribe flag, and expected-observed variants | Can map producer actions to `invoke` and expected arrays to `assert-messages`; no adapter is shipped in v1      |
| VMx conformance catalog          | Prefix-to-chapter table; stable `XXX-NNN` heading IDs; Given/When/Then prose; source-chapter conformance ranges                                       | Normative metadata remains Markdown and marker-tool input; adapter case IDs do not become catalog IDs           |
| DayDreams `app.vm.yaml`          | `vm`, `version`, `description`, `model`, `types`, `operations`, `derived`, `lifecycle`, `conformance`                                                 | YAML remains descriptive; only its linked JSON was translated in the pilot                                      |
| DayDreams `gallery.vm.yaml`      | `vm`, `version`, `description`, `model`, `children`, `state`, `types`, `dependencies`, `operations`, `lifecycle`, `conformance`                       | Not parsed or standardized                                                                                      |
| DayDreams `world.vm.yaml`        | `vm`, `version`, `description`, `model`, `children`, `registry`, `heightfields`, `types`, `operations`, `scene_bridge`, `lifecycle`, `conformance`    | Not parsed or standardized                                                                                      |
| DayDreams AppVM JSON             | `initialRoute`; `cases[]` with `id`, `description`, bespoke `when`, and bespoke `then` fields                                                         | AVM-001/002 were translated to suite fixture plus ordered invoke/state/message steps in the no-push pilot       |
| DayDreams GalleryVM JSON         | `entriesFixture`; `cases[]` with `id`, `description`, `when.op`, `when.args`, and domain-specific `then` fields                                       | Factory/fixture adaptation is feasible but not included                                                         |
| DayDreams WorldVM JSON           | `sceneFixture`, `cases`, `streamingCases`; cases use `id`, optional `description`, `assert`/`equals` or domain-specific `world`, `when`, and `then`   | Multiple setup modes and domain serializers remain consumer-owned; not included                                 |
