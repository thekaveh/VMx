# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package — C# `VMx` v2.6.0,
Python `vmx` v2.6.1, TypeScript `@thekaveh/vmx` v2.6.0, Swift `VMx` v2.6.0
(subset) — declares the spec version it implements. Conformance tests under
`langs/<lang>/tests/conformance/` re-implement the catalog at
`12-conformance.md` and must pass before any flavor releases a stable
version.

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
- `08-aggregate-vm.md` — `AggregateVM<VM1..VM6>` and arity rationale (arity-6 added in v2.2.0).
- `09-forwarding.md` — forwarding decorators.
- `10-builders.md` — builder semantics (immutability, fluent flow).
- `11-threading.md` — foreground/background and scheduler contract.
- `12-conformance.md` — cross-language conformance test catalog (237 IDs).
- `13-tree-utilities.md` — `walk` / `find` / `walk_expanded` tree introspection.

### 1.2 Chapters (v2.0 additions)

- `14-capabilities.md` — 20 opt-in capability micro-interfaces (extended to 22 in v2.1; see §1.3).
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

- `03-messages.md` — §7 Convenience helpers (ADR-0032, informative):
  `PropertyValueChangedMessagesFor` batch publisher.
- `04-commands.md` — §9 "Fluent composition" (ADR-0027): four fluent extension
  methods (`Confirm`, `PrecedeWith`, `SucceedWith`, `WrapWith`) over `ICommand`.
- `14-capabilities.md` — §2.6 `IFilterable<TItem>` (ADR-0022, CAP-021) and §2.10
  `IPageable` (ADR-0023, CAP-022).
- `15-derived-properties.md` — §8 Recipe for avoiding double-subscription on
  lazy initialization.
- `16-notifications.md` — §6–§7 render-side VMs `NotificationVM` and
  `ConfirmationVM` (ADR-0031, NOTIF-011..016) with auto-dismiss lifecycle.

### 1.4 v2.1.x → v2.2.0 changes

v2.2.0 is a minor, non-breaking spec bump motivated by the
[Notes Workspace flagship example portfolio](proposals/2026-05-29-notes-showcase-scenario.md)
(see also `examples/notes-showcase-parity.md`). All v2.1.x consumers continue
to work unchanged.

- **ADR-0034** — extends `AggregateVM` arity to 6. Supersedes ADR-0007 §4's
  "future major" stance on grounds of additivity.
- `08-aggregate-vm.md` — now covers arities 1–6 (was 1–5); adds the arity-6
  row to the members table and extends builder semantics.
- `12-conformance.md` — adds `AGG-006` (arity-6 construction / destruction
  ordering); catalog total goes from 219 to 220.

### 1.5 v2.2.x → v2.3.0 changes

v2.3.0 is a minor, non-breaking spec bump motivated by a comprehensive
builder-pattern audit (see ADR-0035). All v2.2.x consumers continue to work
unchanged; the one behaviour change (C# / Python `CompositeVMBuilder` and
`GroupVMBuilder` now validate `Children` at `Build()`) brings those flavors
into compliance with the existing spec §3 contract and matches TypeScript's
existing behaviour.

- **ADR-0035** — builder pattern audit follow-through: `FormVMBuilder<TM>`
  and `HierarchicalVMBuilder<TModel, TVM>` added across the three v2.3
  flavors (C# / Python / TypeScript — pre-Swift; both are deferred in the
  v2.4 Swift skeleton, see `langs/swift/README.md` §5);
  Children validation for `CompositeVMBuilder` / `GroupVMBuilder` aligned
  with spec; Python + TS gain `with_null_services()` / `withNullServices()`
  Wither parity with C#; Python gains typed-arity
  `DerivedProperty.from_one..from_five` factories.
- `10-builders.md` — §3 table gains rows for `HierarchicalVM<M, VM>` and
  `FormVM<TM>` with required-field contracts; §2 documents `BLD-005`
  additive-retention invariant.
- `12-conformance.md` — adds `BLD-005` (additive setter retention),
  `FORM-011..013` (FormVM builder validate / repeat / defaults), and
  `HIER-015..017` (HierarchicalVM builder validate / repeat / defaults);
  catalog total goes from 220 to 227.

### 1.6 v2.3.x → v2.4.0 changes

v2.4.0 is a minor, non-breaking spec bump that coordinates a publication-readiness pass, a Swift flavor skeleton, an example-app theming scenario contract, and example-app edge-case coverage backfill (see ADR-0036). All v2.3.x consumers continue to work unchanged.

- **ADR-0036** — umbrella for the v2.4.0 release: (a) C# / Python / TS
  publication-readiness (TS npm rename `vmx` → `@thekaveh/vmx` because the
  unscoped name was unavailable; CI workflow polish); (b) Swift flavor
  skeleton at `langs/swift/` covering LIFE / CVM / COMP / GRP / AGG / CMD /
  BLD subsets; (c) Theme as a VM concern — a scenario contract for
  example-app theming wiring `ComponentVM` + `DerivedProperty` +
  `RelayCommand` + `MessageHub` into a `ThemeVM` (no new core types); (d)
  test-coverage backfill (C# Forwarding decorators, Python aggregates,
  edge cases across the three flagship Notes-Showcase apps).
- `12-conformance.md` — adds the `THEME-NNN` family with five scenarios
  (`THEME-001..005`) under §28; catalog total goes from 227 to 232. The
  ThemeVM contract proper lives in `proposals/2026-06-02-theme-vm-scenario.md`.
- Chapter count stays at 22 (no new chapters); the ThemeVM contract is a
  scenario proposal, not a new chapter.

### 1.7 v2.4.x → v2.5.0 changes

v2.5.0 is a minor, non-breaking maintenance bump (see ADR-0037). All
v2.4.x consumers continue to work unchanged.

- **ADR-0037** — maintenance clarifications and additions: hub
  `PropertyName` casing follows the flavor idiom (ch03 §2.1); `Clear()`
  emits `Count` after `Reset` (ch21 §3.3); `ReparentChild` rejects
  self/ancestor cycles (ch18 §5, **HIER-018**); `NotificationHub` dispose
  semantics are normative (ch16 §9, **NOTIF-017**); the Swift lifecycle
  trap is a documented divergence (ch02 §2); the Swift conformance subset
  is recounted 53 → 39 (corrects ADR-0036 §2.E); fixture-prose and
  `NULL-*` listing corrections (ch15 §7, ch03 §8, ch11 §6).
- `12-conformance.md` — adds `HIER-018` and `NOTIF-017`; catalog total
  goes from 232 to 235 (230 library + 5 THEME scenario IDs).
- Chapter count stays at 22.

### 1.8 v2.5.x → v2.6.0 changes

v2.6.0 is a minor, non-breaking maintenance bump from the absorption-audit
follow-up (see ADRs 0039 / 0040 / 0041 / 0042 and
`proposals/2026-06-13-vmx-absorption-audit-followup.md`). All v2.5.x
consumers continue to work unchanged.

- **ADR-0039** — `INotifyPropertyChanging` not supported (teaching note;
  no code change).
- **ADR-0040** — `IProperty<T>` reactive backing-field not adopted
  (teaching note; no code change).
- **ADR-0041** — Single disposable lifecycle, no two-tier bags (teaching
  note; no code change).
- **ADR-0042** — `CompositeVMBuilder.Current(selector)` +
  `OnCurrentChanged(callback)` declarative selection hooks on the
  composite builders (behavior change, additive). Implemented across C# /
  Python / TypeScript on both modeled and non-modeled builders; Swift
  ships on the non-modeled builder (modeled composite is outside Swift's
  documented subset).
- `06-composite-vm.md` — §3.2 documents the builder selection hooks.
- `12-conformance.md` — adds `COMP-025` (`current(selector)` invariants)
  and `COMP-026` (`onCurrentChanged(callback)` invariants); catalog total
  goes from 235 to 237 (232 library + 5 THEME scenario IDs).
- Chapter count stays at 22.

### 1.9 Supporting artefacts

- `VERSION` — current spec SemVer (`2.6.0`).
- `fixtures/` — machine-checkable test inputs (JSON, 4 files).
- `ADRs/` — Architecture Decision Records (0001-0042); see
  [`ADRs/README.md`](ADRs/README.md) for the registry index.
- `proposals/` — historical planning artifacts (accepted proposals that landed
  in past releases); not part of the published spec.

## 2. Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor
declares the spec version it implements (see
[`../compatibility-matrix.md`](../compatibility-matrix.md)). Breaking spec
changes require a major-version bump in every active flavor.

The historical design rationale lives in the ADRs alongside this spec.
