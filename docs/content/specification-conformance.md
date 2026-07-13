# 10. Specification & Conformance

The VMx behavior contract starts in `spec/`, not in any single language
implementation.

## Source Of Truth

- Spec index:
  [spec/README.md](../../spec/README.md)
- Current spec version:
  [spec/VERSION](../../spec/VERSION)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## What Lives In The Spec

- 24 numbered chapters from `00-overview.md` through `23-async-resource-vm.md`
- ADRs describing behavior and design decisions
- shared JSON fixtures consumed by the language flavors
- the cross-language conformance catalog in `spec/12-conformance.md`

## Conformance Model

The current catalog contains:

- 391 library IDs implemented by all five full-parity source flavors
- 5 `THEME-00x` scenario IDs exercised by the flagship example apps
- 396 total IDs in the published catalog

The source overview is here:
[spec/12-conformance.md](../../spec/12-conformance.md).

## How The Repo Enforces It

- Each language flavor carries a conformance suite under its own tree.
- `tools/check-conformance-coverage.py` enforces full library coverage across
  C#, Python, TypeScript, Swift, and Rust.
- The examples workflows enforce the separate flagship scenario contract.

## Consumer Adapter Suites

VMx TypeScript 3.21.0 adds the optional
`@thekaveh/vmx/conformance` entry point. It validates and executes
consumer-owned operation/assertion suites without making those suites part of
the normative VMx behavior catalog. The root `@thekaveh/vmx` entry does not
export this tooling or load its Ajv validator.

The canonical schema is
`spec/schemas/consumer-conformance-v1.schema.json`. It is a non-normative,
independently versioned adapter contract governed by ADR-0102.

### Discovery And Gap Table

VMx's fixtures, the conformance catalog, and DayDreams' consumer files have
different responsibilities. Adapter v1 standardizes only their executable
boundary.

| Concern           | VMx fixtures/catalog                                              | DayDreams YAML/JSON                                                                                | Adapter v1 decision                                                    |
| ----------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Version           | `$schema-version` on four JSON fixtures                           | YAML `version`; JSON fixtures unversioned                                                          | Require `$schema-version: "1.0.0"` on executable suites                |
| Identity          | Fixture-specific `id`/`name`; catalog headings hold normative IDs | JSON cases hold AVM/GVM/WVM IDs                                                                    | Require a stable case `id`; IDs remain consumer-owned                  |
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

### Suite Shape

Unknown structural fields fail validation. Fixtures, invocation arguments,
expected state, and normalized messages accept arbitrary JSON values.

```json
{
  "$schema-version": "1.0.0",
  "suite": "app-vm",
  "fixture": { "initialRoute": "gallery" },
  "cases": [
    {
      "id": "AVM-001",
      "steps": [
        { "kind": "invoke", "operation": "navigate", "args": ["world"] },
        {
          "kind": "assert-state",
          "path": "/model/route",
          "equals": "world"
        },
        {
          "kind": "assert-messages",
          "equals": [
            {
              "type": "PropertyChangedMessage",
              "propertyName": "model",
              "senderName": "appVm"
            }
          ]
        }
      ]
    }
  ]
}
```

`assert-state` uses RFC 6901 decoding and distinguishes a missing path from a
present `null`. Object key order is irrelevant; array and message order are
exact. `assert-messages` drains the adapter once for each assertion.

### Factory And Runner

The runner owns sequencing and teardown; the consumer owns construction,
operation dispatch, JSON snapshots, and message normalization.

```ts
import {
  parseConsumerConformance,
  runConsumerConformance,
  type ConsumerConformanceFactory,
} from "@thekaveh/vmx/conformance";

const factory: ConsumerConformanceFactory = ({ caseFixture }) => {
  const vm = createAppVm(caseFixture);
  return {
    invoke: async (operation, args) => invokeApp(vm, operation, args),
    snapshot: () => snapshotApp(vm),
    drainMessages: () => messageRecorder.drain(),
    dispose: () => vm.dispose(),
  };
};

const suite = parseConsumerConformance(input);
const report = await runConsumerConformance(suite, factory);
```

`runConsumerConformanceCase` integrates one case with any test framework.
`runConsumerConformance` executes all cases sequentially and returns passed and
failed results. The runner imports no Vitest or Jest API.

Factory, operation, state, message, and disposal failures include actionable
instance paths. Disposal runs exactly once in `finally`; if execution and
disposal both fail, the execution error stays primary and retains the teardown
cause.

`adaptCommandTruthTableFixture` demonstrates adapting every unchanged VMx
command fixture row. The existing CMD-007 test and all five-flavor conformance
coverage remain in place.

### Non-Goals And Follow-Up Gate

Adapter v1 does not parse YAML, define a VMx viewmodel dialect, generate tests,
or generate Swift. A Swift or code-generation proposal needs a separate ADR,
successful use by two independent consumers, a native Swift factory without
TypeScript assumptions, and a maintained domain-type mapping that makes
generation safer than manual implementation.

## Test Marker Grammar

The coverage checker recognizes one intentional marker form per flavor:

| Flavor     | Marker                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------- |
| C#         | `[Trait("Conformance", "LIFE-001")]`                                                     |
| Python     | `@pytest.mark.conformance("LIFE-001")`                                                   |
| TypeScript | `describe("LIFE-001", ...)`                                                              |
| Swift      | `// LIFE-001 — description` or `/// LIFE-001 — description`, attached to a test function |
| Rust       | `/// LIFE-001 — description` attached through `#[test]` to a test function               |

For Rust, the ID must be the first token after `///` and an em dash must follow
it on the same line. Only doc-comment and attribute lines may separate the
marker from `#[test]` and its function. Ordinary comments, file summaries,
unattached markers, and markers in block-commented tests are ignored. Duplicate
markers are one set-based coverage claim. In required mode, a missing Rust ID is
listed under `MISSING` and fails the coverage command.

## Practical Reading Path

1. Read `spec/README.md` for chapter ownership and release history.
1. Read the primitive pages on this site for a faster conceptual map.
1. Use the flavor README when you need package details or host-specific
   examples.
1. Use the parity matrix and conformance catalog when you need proof rather than
   overview.
