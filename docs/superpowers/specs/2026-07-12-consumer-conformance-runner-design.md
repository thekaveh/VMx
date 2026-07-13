# Consumer Conformance Runner Design

**Issue:** #95\
**Status:** Approved for implementation by the continuous roadmap directive\
**Target:** TypeScript 3.21.0 implementing VMx spec 3.20.0

## 1. Problem and corrected scope

VMx owns four purpose-built JSON fixtures and a conformance-marker catalog.
DayDreams owns three YAML viewmodel descriptions, three unrelated JSON fixture
shapes, and hand-written Vitest dispatch/assertion loops. They do not share a
schema today. Treating the DayDreams YAML dialect as an existing VMx standard
would turn product prose and TypeScript type expressions into a false normative
contract.

This ticket introduces a non-normative **adapter schema** plus a
test-framework-neutral TypeScript runner. Consumers map their own source
fixtures and viewmodels into the adapter contract. VMx does not interpret YAML,
generate code, or claim that the adapter schema specifies a viewmodel.

## 2. Discovery and gap table

| Concern           | VMx fixtures/catalog                                                   | DayDreams YAML/JSON                                                                                | Adapter v1 decision                                                          |
| ----------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Version           | `$schema-version` on four JSON fixtures                                | YAML `version`; JSON fixtures unversioned                                                          | Require `$schema-version: "1.0.0"` on executable suites                      |
| Identity          | fixture-specific `id`/`name`; catalog headings carry normative IDs     | JSON cases carry AVM/GVM/WVM IDs                                                                   | Require stable case `id`; IDs remain consumer-owned                          |
| Description       | free text on some scenarios                                            | YAML and JSON descriptions                                                                         | Optional suite/case descriptions                                             |
| Setup             | fixture-specific root fields such as states, transforms, or scene path | `initialRoute`, `entriesFixture`, `sceneFixture`, streaming setup                                  | Opaque JSON `fixture` at suite and case levels, passed to the factory        |
| Operations        | `via`, mutation tuples, producer sends, predicate/task flags           | YAML `operations`; JSON `when.op` with bespoke payloads                                            | Ordered `invoke` steps with operation name and JSON argument array           |
| State             | fixture-specific expected fields                                       | bespoke `then` keys                                                                                | `assert-state` with RFC 6901 JSON Pointer and JSON equality                  |
| Messages          | message-ordering arrays and conformance prose                          | encoded trace strings such as `PropertyChangedMessage:model@appVm`                                 | `assert-messages` exact ordered JSON records drained from the adapter        |
| Async             | no shared execution shape                                              | no generic async contract                                                                          | Every factory/invoke/dispose result is awaited before the next step          |
| Errors            | lifecycle `legal`; test code owns exceptions                           | bespoke harness branches                                                                           | Schema validation and execution errors include suite/case/step JSON paths    |
| Teardown          | each flavor test owns cleanup                                          | each test calls `dispose()`                                                                        | Runner calls adapter `dispose` exactly once in `finally`, including failures |
| YAML model fields | none                                                                   | `vm`, `model`, `types`, `children`, `state`, `dependencies`, `derived`, `lifecycle`, `conformance` | Informative discovery only; only the linked JSON is adapted                  |
| Code generation   | none                                                                   | prose says Swift may later regenerate                                                              | Explicitly out of scope                                                      |

## 3. Canonical schema

Create `spec/schemas/consumer-conformance-v1.schema.json`. Its `$comment`
states that it is a versioned, language-neutral adapter contract and not a
normative VMx behavior chapter. A suite contains:

```json
{
  "$schema-version": "1.0.0",
  "suite": "app-vm",
  "description": "optional",
  "fixture": {},
  "cases": [
    {
      "id": "AVM-001",
      "description": "optional",
      "fixture": {},
      "steps": [
        { "kind": "invoke", "operation": "navigate", "args": [] },
        { "kind": "assert-state", "path": "/model/route", "equals": {} },
        { "kind": "assert-messages", "equals": [] }
      ]
    }
  ]
}
```

Unknown structural fields fail validation. JSON values remain unrestricted
inside fixtures, arguments, expected state, and normalized messages. This keeps
the executable protocol strict without pretending VMx owns consumer domain
types.

## 4. TypeScript public surface

Add the separately importable `@thekaveh/vmx/conformance` entry point. It is
excluded from the root entry and exports:

- JSON value, suite, case, step, adapter, factory, result, and report types;
- `consumerConformanceSchema`;
- `parseConsumerConformance(input)`;
- `runConsumerConformanceCase(suite, testCase, factory)` for Vitest/Jest loops;
- `runConsumerConformance(input, factory)` for sequential whole-suite runs;
- typed validation and execution errors with stable diagnostic paths; and
- `adaptCommandTruthTableFixture(input)` as one concrete adapter for an
  existing VMx fixture.

The runner imports no Vitest/Jest API. Ajv validates draft-2020-12 JSON Schema
with all errors enabled. The conformance entry bundles Ajv; the root VMx entry
does not import or re-export it.

## 5. Factory and execution contract

The factory receives suite metadata, the selected case, the suite fixture, and
the optional case fixture. It returns an adapter with:

```text
invoke(operation, args) -> value or awaitable value
snapshot() -> JSON value
drainMessages() -> ordered JSON object array
dispose() -> void or awaitable void
```

Cases and steps run in declaration order. Every invoke is awaited. State paths
use RFC 6901 decoding and fail at the step path when a segment is absent.
State/message equality is structural JSON equality, independent of object key
order. `assert-messages` drains once and compares the exact ordered records.

The runner installs teardown immediately after factory success and calls it
exactly once in `finally`. Factory failure, operation failure, state mismatch,
message mismatch, missing path, and teardown failure retain the suite ID, case
ID, step index, and schema-style instance path. A teardown error never hides an
earlier execution error.

## 6. Existing-fixture adaptation

`adaptCommandTruthTableFixture` converts the unchanged
`spec/fixtures/command-truthtable.json` rows into adapter-v1 cases. Each row is
the case fixture; the generated steps invoke `execute` and assert normalized
`canExecute`, `taskInvoked`, and `canExecuteChanged` state. VMx's existing
CMD-007 test remains in place, so five-flavor coverage is not weakened or
redirected to this TypeScript-only tool.

## 7. DayDreams pilot

Use a disposable clone and a locally packed VMx tarball. Convert
`app-conformance.json` to adapter v1 without changing `app.vm.yaml` or AppVM.
Replace only the two-case hand-written operation/assertion loop with factory
registration and per-case runner calls. Keep AVM-SENDER, AVM-NATIVE, and other
non-fixture tests unchanged.

Record fixture conversion, deleted/added harness LOC, exact test/typecheck
commands, and gaps. Never push the consumer clone.

## 8. Versioning, documentation, and non-goals

The additive TypeScript subpath releases as 3.21.0 while continuing to
implement spec 3.20.0. Update package exports/lock/version, TypeScript changelog
and README, compatibility matrix, root status, canonical specification and
conformance docs, ADR-0102, and generated site/wiki surfaces. Add no normative
conformance IDs.

No YAML parser, YAML schema, Swift runner, Swift skeleton, or generator is
included. A Swift/codegen follow-up requires a separate ADR plus evidence that
the adapter schema works in at least two independent consumers, a native Swift
factory can implement it without TypeScript assumptions, and a real consumer
has a maintained domain-type mapping that makes generation safer than manual
implementation.
