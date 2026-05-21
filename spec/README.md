# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package (C# `VMx`, Python `vmx`, future
TypeScript `vmx`) declares the spec version it implements. Conformance tests under
`langs/<lang>/tests/conformance/` re-implement the catalog at `12-conformance.md` and
must pass before any flavor releases a stable version.

## Contents

- `00-overview.md` — vision, scope, glossary.
- `01-concepts.md` — VM hierarchy, MVVM role, dependency philosophy.
- `02-lifecycle.md` — `ConstructionStatus` state machine and invariants.
- `03-messages.md` — message hub semantics, ordering, threading.
- `04-commands.md` — command contract, predicates, reactive triggers.
- `05-component-vm.md` — `ComponentVM` (readonly and modeled variants).
- `06-composite-vm.md` — `CompositeVM` (selectable children, `Current`).
- `07-group-vm.md` — `GroupVM`.
- `08-aggregate-vm.md` — `AggregateVM<VM1..VM5>` and arity rationale.
- `09-forwarding.md` — forwarding decorators.
- `10-builders.md` — builder semantics (immutability, fluent flow).
- `11-threading.md` — foreground/background and scheduler contract.
- `12-conformance.md` — cross-language conformance test catalog.
- `VERSION` — current spec SemVer.
- `fixtures/` — machine-checkable test inputs (JSON).
- `ADRs/` — Architecture Decision Records.

## Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor declares
the spec version it implements (see [`../compatibility-matrix.md`](../compatibility-matrix.md)).
Breaking spec changes require a major-version bump in every active flavor.

See the design doc at `../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`
for the full background.
