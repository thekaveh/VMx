# Issue #95 DayDreams AppVM pilot

## 1. Scope

- Consumer: `thekaveh/daydreams` at `8d314dd`.
- VMx source: issue branch at `6467b10`, packaged as
  `@thekaveh/vmx@3.21.0`.
- Tarball SHA-256:
  `c937f9fb7e93734043c977bb50b7f4c480729f20c70eacf2be9d23bf6f064812`.
- Pilot target: the two fixture-backed AppVM cases, AVM-001 and AVM-002.
- Preserved tests: AVM-SENDER and AVM-NATIVE remained unchanged and passed.
- Location: disposable clone `/tmp/vmx-issue95-daydreams`; no consumer commit
  or push was created.

The consumer's `app.vm.yaml` and AppVM behavior were not changed. The JSON
fixture was translated to adapter schema v1, and the test registered one
consumer factory with `runConsumerConformanceCase`.

## 2. Red Evidence

After translating the fixture but before replacing the bespoke harness:

```text
bun test packages/viewmodel/tests/appVm.test.ts
2 passed, 2 failed
TypeError: undefined is not an object (evaluating 'c.when.op')
```

The old harness therefore could not silently accept the new schema.

Installing the packed current VMx also exposed an independent consumer
compatibility migration:

```text
bun run --cwd packages/viewmodel typecheck
TS2610: 'hub' is defined as an accessor ... but is overridden ... as an
instance property
```

DayDreams repeated that override in six viewmodels. In the disposable clone,
each field/assignment pair became an accessor override delegating to
`super.hub`. These 12 removed lines and 6 added lines are not counted as
conformance-harness LOC.

## 3. Green Evidence

```text
bun test packages/viewmodel/tests/appVm.test.ts
4 passed, 0 failed

bun run --cwd packages/viewmodel typecheck
tsc --noEmit

bun run --cwd packages/viewmodel test
10 files passed; 141 tests passed
```

AVM-001 exercised ordered navigation, RFC 6901 state lookup, and one exact
normalized `PropertyChangedMessage` record. AVM-002 exercised initial state and
two ordered operations with intermediate assertions. Factory teardown owned
the hub subscription and AppVM disposal.

## 4. LOC Measurement

Measured with `git diff --numstat` against DayDreams `8d314dd`:

| File                                             | Added | Deleted | Net |
| ------------------------------------------------ | ----: | ------: | --: |
| `packages/viewmodel/tests/appVm.test.ts`         |    48 |      34 | +14 |
| `specs/viewmodels/fixtures/app-conformance.json` |    44 |      13 | +31 |
| Combined fixture and test                        |    92 |      47 | +45 |

The test file grew from 80 to 94 lines; the fixture grew from 24 to 55 lines.
The pilot deletes the case-shape interfaces and both case-specific branching
paths, but replaces them with an explicit 33-line AppVM factory and normalized
message recorder. For this two-case suite, adapter v1 does **not** reduce net
LOC. Its measured benefit is strict validation, uniform ordered assertions,
path diagnostics, and deterministic teardown. Factory cost can amortize across
larger case sets, but this pilot does not claim that result.

## 5. Findings And Follow-Up Gate

- Message assertions still require a consumer-owned normalization policy; VMx
  correctly does not serialize arbitrary sender/model graphs.
- Explicit step sequences are more verbose than DayDreams' two bespoke
  `when`/`then` objects but remove hidden harness branching.
- The package surfaced a real inherited-accessor migration that vendored-source
  consumption had not exposed through this clone's prior install state.
- YAML remains descriptive input only. The pilot provides no evidence for a
  VMx YAML dialect.
- One TypeScript consumer is insufficient evidence for Swift or code
  generation. ADR-0102's two-consumer, native-Swift-factory, and maintained
  type-mapping gates remain unmet.
