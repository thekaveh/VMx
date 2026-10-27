# 10. Specification & Conformance

The VMx behavior contract starts in `spec/`, not in any single language
implementation.

## 10.1. Source Of Truth

- Spec index:
  [spec/README.md](../../spec/README.md)
- Current spec version:
  [spec/VERSION](../../spec/VERSION)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## 10.2. What Lives In The Spec

- 24 numbered chapters from `00-overview.md` through `23-async-resource-vm.md`
- ADRs describing behavior and design decisions
- shared JSON fixtures consumed by the language flavors
- the cross-language conformance catalog in `spec/12-conformance.md`

## 10.3. Conformance Model

The catalog contains:

- 431 library IDs implemented by all five catalog-complete source flavors
- 5 `THEME-00x` scenario IDs exercised by the flagship example apps
- 436 total IDs in the published catalog

The source overview is here:
[spec/12-conformance.md](../../spec/12-conformance.md).

Catalog completeness is a source statement: every library ID has a marked
test in every flavor. Executed evidence, below, shows that each marked test ran
and passed. The
[Rust parity ledger](../maintenance/2026-07-16-rust-capability-parity.md)
(open items and recorded differences in §12.4.7 and §12.7–§12.12) adds focused member and
edge-behavior evidence for Rust.

### 10.3.1. Catalog, Execution, And Behavioral Evidence

Three separate statements describe a flavor's conformance:

1. **Catalog completeness.** Every library ID has a marker on a test in the
   flavor's sources. `tools/check-conformance-coverage.py` checks this without
   running anything.
1. **Executed evidence.** A runner discovered, executed, and passed at least one
   test for every library ID. `tools/check-conformance-execution.py` reads the
   runner's own report and checks this.
1. **Behavioral strength.** A test's assertions would catch a violation of the
   behavior its ID names. Reviewers judge this; no tool proves it.

Neither of the first two implies the third, and none of them is member-level
parity between flavors. For Rust ownership-assertion conventions, see
[Rust Ownership-Test Conventions](contributing-releases.md#1135-rust-ownership-test-conventions).

The execution check maps each executed case to its IDs. Python records each
`conformance` marker as a JUnit property, and TypeScript uses a `describe`
title that is exactly the ID. C#, Swift, and Rust match the reported class and
function to the test that carries the source marker, with no name-only
fallback, so a same-named test elsewhere is never credited. For each ID:

- the ID **fails** if any executed case for it failed;
- the ID **passes** if none failed and at least one passed;
- the ID is **skipped** if every case for it was skipped;
- the ID is **missing** if no executed case carries it.

Only a passing ID qualifies. Parameterized variants and duplicate reports each
count, so a failing variant fails the ID and a skipped variant is ignored. A
report that cannot be parsed, is truncated, disagrees with its own totals, or
records a collection or build failure is rejected rather than read as success.

Each flavor workflow uploads a `conformance-evidence-<flavor>-<configuration>`
artifact with the runner report and a JSON file that maps every library ID to
its executed cases and outcomes, stamped with the commit, toolchain, and
configuration:

| Flavor     | Report                                              | Evidenced cells                  |
| ---------- | --------------------------------------------------- | -------------------------------- |
| C#         | TRX from `dotnet test --logger trx`, all frameworks | Linux and macOS                  |
| Python     | JUnit XML from `pytest --junitxml`                  | every OS and Python version      |
| TypeScript | JUnit XML from Vitest's `junit` reporter            | Linux and macOS, every Node line |
| Swift      | xUnit XML from `swift test --xunit-output`          | both Xcode cells                 |
| Rust       | libtest output from `cargo test`                    | Linux and macOS                  |

Windows cells run the same tests, but the C#, TypeScript, and Rust jobs have no
reliable `python3` there, so they publish no separate evidence. SwiftPM's xUnit
report does not mark XCTest skips. The Swift conformance suite uses no
`XCTSkip`, so a skipped Swift case cannot pass for executed.

## 10.4. How The Repo Enforces It

- Each language flavor carries a conformance suite under its own tree.
- `tools/check-conformance-coverage.py` enforces full library coverage across
  C#, Python, TypeScript, Swift, and Rust.
- `tools/check-conformance-execution.py` requires a passing executed case for
  every library ID in each flavor workflow.
- The examples workflows enforce the separate flagship scenario contract. Two
  shared scenario files run in all four flagship suites: a Notes workspace
  lifecycle (`examples/notes-showcase-scenario.json`) and the five `THEME-00x`
  scenarios in order (`examples/notes-showcase-theme-scenario.json`). The shared scenarios
  compare semantic outcomes, not just test names, and add no catalog IDs.

Coverage floors, catalog markers, and assertion strength are separate evidence.
A marker assigns a test to a catalog ID. An assertion shows that the test would
catch a violation. A coverage floor shows how much library code the suites run.
No one of them implies the others. See
[Coverage Floors](contributing-releases.md#1133-coverage-floors).

## 10.5. Consumer Adapter Suites

The optional TypeScript entry point `@thekaveh/vmx/conformance` validates and
executes consumer-owned operation/assertion suites. Those suites do not become
part of the normative VMx behavior catalog. The root `@thekaveh/vmx` entry does not
export this tooling or load its Ajv validator.

The canonical schema is
`spec/schemas/consumer-conformance-v1.schema.json`. It is a non-normative,
independently versioned adapter contract governed by ADR-0102.

### 10.5.1. Suite Shape

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

### 10.5.2. Factory And Runner

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

`adaptCommandTruthTableFixture` adapts every row of the VMx command truth-table
fixture without changing it. The adapter does not replace the `CMD-007` test or
the five-flavor conformance suites.

### 10.5.3. Non-Goals And Follow-Up Gate

Adapter v1 does not parse YAML, define a VMx viewmodel dialect, generate tests,
or generate Swift. A Swift or code-generation proposal needs a separate ADR,
successful use by two independent consumers, a native Swift factory without
TypeScript assumptions, and a maintained domain-type mapping that makes
generation safer than manual implementation.

## 10.6. Test Marker Grammar

The coverage checker recognizes one intentional marker form per flavor:

| Flavor     | Marker                                                                                   |
| ---------- | ---------------------------------------------------------------------------------------- |
| C#         | `[Trait("Conformance", "LIFE-001")]`                                                     |
| Python     | `@pytest.mark.conformance("LIFE-001")`                                                   |
| TypeScript | `describe("LIFE-001", ...)`                                                              |
| Swift      | `// LIFE-001 — description` or `/// LIFE-001 — description`, attached to a test function |
| Rust       | `/// LIFE-001 — description` attached through `#[test]` to a test function               |

The Rust attachment rules, including which comments the checker ignores, are in
[tools/README.md](../../tools/README.md).

In required mode, a marker for an ID the catalog does not define is listed under
`ORPHAN` and fails the coverage command for that flavor. It claims coverage of
nothing, and usually means a renamed or retired ID whose real test lost its
marker. Without `--require`, the report still lists it for information.

## 10.7. Practical Reading Path

1. Read `spec/README.md` for chapter ownership and `spec/HISTORY.md` for release
   history.
1. Read the primitive pages on this site for a faster conceptual map.
1. Use the flavor README when you need package details or host-specific
   examples.
1. Use the parity matrix and conformance catalog when you need proof rather than
   overview.

## 10.8. Controlled Concurrency Interleavings

Concurrency regressions acknowledge the exact runtime boundary that creates the
tested ordering; a worker-start signal or an elapsed timeout is not evidence.
See
[Reproduce Controlled Interleavings](contributing-releases.md#1131-reproduce-controlled-interleavings)
for commands and `docs/maintenance/2026-09-24-controlled-interleavings-audit.md`
for scope and limitations.
