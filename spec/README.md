# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package — C# `VMx` v2.0.0,
Python `vmx` v2.0.0, TypeScript `vmx` v2.0.0 — declares the spec version it
implements. Conformance tests under `langs/<lang>/tests/conformance/`
re-implement the catalog at `12-conformance.md` and must pass before any
flavor releases a stable version.

## 1. Contents

### 1.1 Chapters (foundational, v1.x)

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
- `12-conformance.md` — cross-language conformance test catalog (213 IDs).
- `13-tree-utilities.md` — `walk` / `find` / `walk_expanded` tree introspection.

### 1.2 Chapters (v2.0 additions)

- `14-capabilities.md` — 22 opt-in capability micro-interfaces (incl. `IFilterable<T>` and `IPageable`).
- `15-derived-properties.md` — `DerivedProperty<TValue>` N-source computed values.
- `16-notifications.md` — opt-in `INotificationHub` sub-package.
- `17-localization.md` — `ILocalizer` hook + `NullLocalizer` default.

### 1.3 Chapters (v2.1 additions)

- `18-hierarchical-vm.md` — `HierarchicalVM<TModel, TVM>`: first-class recursive
  tree VM with lazy/eager children, depth-first construction, materialized path,
  and `TreeStructureChangedMessage`.
- `19-dialogs.md` — `IDialogService`: host-side contract for modal interactions
  (file pick, confirm prompt, severity-tagged notify). `NullDialogService`
  per ADR-0017.
- `20-form-vm.md` — `FormVM<TM>`: snapshot/revert edit lifecycle (ORM-agnostic);
  `DenyCommand`, `ApproveCommand`, `OnApproved`, strict mode.
- `21-collections.md` — opt-in collection primitives: `ServicedObservableCollection<T>`,
  `ObservableList<T>`, `ObservableDictionary`, `PagedComposition<TVM>`.

The following existing chapters were also extended in v2.1:

- `04-commands.md` — §9 "Fluent composition" (ADR-0027): four fluent extension
  methods (`Confirm`, `PrecedeWith`, `SucceedWith`, `WrapWith`) over `ICommand`.
- `14-capabilities.md` — §2.6 `IFilterable<T>` (ADR-0022, CAP-021) and §2.10
  `IPageable` (ADR-0023, CAP-022).

### 1.4 Supporting artefacts

- `VERSION` — current spec SemVer (`2.1.0-dev`).
- `fixtures/` — machine-checkable test inputs (JSON, 4 files).
- `ADRs/` — Architecture Decision Records (0001-0028); see
  [`ADRs/README.md`](ADRs/README.md) for the registry index.
- `proposals/` — deferred designs not yet promoted to chapters.

## 2. Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor
declares the spec version it implements (see
[`../compatibility-matrix.md`](../compatibility-matrix.md)). Breaking spec
changes require a major-version bump in every active flavor.

The historical design rationale lives in the ADRs alongside this spec.
