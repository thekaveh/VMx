# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package declares the spec
version it implements; see [`compatibility-matrix.md`](../compatibility-matrix.md)
for current per-flavor versions. Each flavor's registered conformance suite
re-implements the catalog at `12-conformance.md`: C# under
`langs/csharp/tests/VMx.Conformance.Tests`, Python under
`langs/python/tests/conformance`, TypeScript under
`langs/typescript/tests/conformance`, Swift under `langs/swift/Tests/VMxTests`,
and Rust under `langs/rust/tests/conformance`. Behavioral conformance must pass
before any flavor releases a stable version.

## 1. Contents

### 1.1 Chapters

- `00-overview.md` — vision, scope, glossary.
- `01-concepts.md` — VM hierarchy, MVVM role, dependency philosophy.
- `02-lifecycle.md` — `ConstructionStatus` state machine and invariants.
- `03-messages.md` — message hub semantics, ordering, threading.
- `04-commands.md` — command contract, predicates, reactive triggers, fluent
  composition.
- `05-component-vm.md` — `ComponentVM` (readonly and modeled variants).
- `06-composite-vm.md` — `CompositeVM` (selectable children, `Current`).
- `07-group-vm.md` — `GroupVM`.
- `08-aggregate-vm.md` — `AggregateVM<VM1..VM6>` and arity rationale.
- `09-forwarding.md` — forwarding decorators.
- `10-builders.md` — builder semantics (immutability, fluent flow).
- `11-threading.md` — foreground/background and scheduler contract.
- `12-conformance.md` — cross-language conformance test catalog (449 IDs).
- `13-tree-utilities.md` — `walk` / `find` / `walk_expanded` tree introspection.
- `14-capabilities.md` — 22 opt-in capability micro-interfaces.
- `15-derived-properties.md` — `DerivedProperty<TValue>` N-source computed values.
- `16-notifications.md` — opt-in `INotificationHub` sub-package and the
  `NotificationVM` / `ConfirmationVM` render-side VMs.
- `17-localization.md` — `ILocalizer` hook + `NullLocalizer` default.
- `18-hierarchical-vm.md` — `HierarchicalVM<TModel, TVM>`: recursive tree VM
  with lazy/eager children, depth-first construction, materialized path,
  `TreeStructureChangedMessage`, and the opt-in `TreeSelection` helper.
- `19-dialogs.md` — `IDialogService`: host-side contract for modal
  interactions (file pick, confirm prompt, severity-tagged notify) and
  `NullDialogService`.
- `20-form-vm.md` — `FormVM<TM>`: snapshot/revert edit lifecycle;
  `DenyCommand`, `ApproveCommand`, `OnApproved`, strict mode.
- `21-collections.md` — opt-in collection primitives:
  `ServicedObservableCollection<T>`, `ObservableList<T>`,
  `ObservableDictionary`, `PagedComposition<TVM>`, and related collections.
- `22-discriminator-vm.md` — active-key / modal-overlay state coordinator.
- `23-async-resource-vm.md` — one-value asynchronous presentation lifecycle,
  cancellation, stale-result suppression, retention, and optional cleanup.

### 1.2 Supporting artefacts

- `VERSION` — current spec SemVer (`3.30.0`).
- `HISTORY.md` — the changes of each spec release.
- `fixtures/` — machine-checkable test inputs (JSON, 4 files).
- `ADRs/` — Architecture Decision Records (0001-0166); see
  [`ADRs/README.md`](ADRs/README.md) for the registry index.
- `schemas/` — versioned supporting machine contracts. The consumer
  conformance v1 schema is non-normative; see ADR-0102.
- `proposals/` — planning artifacts (accepted proposals that landed in past
  releases). These are **mostly historical and not part of the published
  normative spec**, with one documented exception: a proposal MAY carry a
  **scenario contract** that `12-conformance.md` references normatively. The
  ThemeVM scenario contract (`proposals/2026-06-02-theme-vm-scenario.md`,
  ADR-0036 §2.C) is such a case — its `THEME-001..THEME-005` IDs are normative
  for any flavor or example app that implements the contract (`12-conformance.md`
  §29). Where `12-conformance.md` cites a proposal, that proposal's referenced
  scenario contract is normative even though the surrounding proposal prose is
  not (ADR-0051).

## 2. Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor
declares the spec version it implements (see
[`../compatibility-matrix.md`](../compatibility-matrix.md)). Breaking spec
changes require a major-version bump in every active flavor.

The design rationale lives in the ADRs alongside this spec.
[`HISTORY.md`](HISTORY.md) records the changes of each spec release.
