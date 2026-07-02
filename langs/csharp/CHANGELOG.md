# Changelog

All notable changes to the C# flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps C# at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommand<T>` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.
- Pinned common options-factory conformance (`BLD-006`) and group-child
  non-selection semantics (`GRP-011`).

### Fixed

- `ConstructAsync()` / `DestructAsync()` now complete when a background hook
  failure rolls back to the prior settled lifecycle state instead of waiting
  only for the happy-path terminal state.
- Concurrent `Dispose()` calls invoke `OnDispose()` at most once.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes.
- Group children no longer report enabled child selection into a group, and
  composite/group lifecycle cascades snapshot children before invoking hooks.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** — a breaking release that hardens the
lifecycle/dispose concurrency path and reconciles the public surface across
flavors. Implements `spec-v3.0.0`. See ADRs 0047–0058 and
`docs/audit/2026-06-27-vmx-merged-critique.md`.

### Added

- Positional-options construction for the common VMs — a static `Create(options)`
  factory alongside the unchanged fluent builders, taking an options `record`:
  `ComponentVM.Create(new ComponentVMOptions { … })`,
  `ComponentVM<M>.Create(new ComponentVMOptions<M> { … })`,
  `CompositeVM<VM>.Create(new CompositeVMOptions<VM> { … })`,
  `GroupVM<VM>.Create(new GroupVMOptions<VM> { … })`. Delegates to the builder, so
  required-field validation (`BuilderValidationException`) and the resulting VM are
  identical to the fluent path (ADR-0055; VMX-020).
- `IAsyncCommand` / `AsyncRelayCommand` — an additive async command that flows a
  `CancellationToken` into a long-running task and adds a `Cancel()` method,
  closing the cancellation gap the synchronous `RelayCommand` had. Cancellation is
  non-throwing to the caller by default with an opt-in throwing mode; fire-and-forget
  task faults route to an `Errors` observable. `RelayCommand` is unchanged
  (ADR-0056; CMD-012; VMX-052).
- `FormVM<TM>` surfaces approve-path persister failures on a new `ApproveErrors`
  observable instead of swallowing them; `IsDirty` uses the model's own value
  equality and the default snapshot is a deep value-copy (`System.Text.Json`
  round-trip), both injectable; `OnApproved` is pinned to the persisted value
  (ADR-0048; FORM-015).

### Removed

- **BREAKING:** Removed `VMx.Extensions.LinqHelpers`
  (`CartesianProduct`/`Sample`/`Product`) — general-purpose LINQ combinators
  unrelated to the viewmodel domain, referenced by nothing but their own tests
  (ADR-0052; VMX-068). Inline the one-line LINQ equivalents in the consuming
  project if needed.

### Changed

- **BREAKING:** `ConfirmationDecoratorCommand.Execute()` (synchronous
  fire-and-forget) now surfaces a rejecting `confirm` delegate or a throwing inner
  command on a new `Errors` observable instead of swallowing them — the C# swallow
  is fixed for cross-flavor parity; the awaitable `ExecuteAsync()` keeps its throw
  behavior (ADR-0049; CMDD-010). `ModeledCrudCommands` Update/Delete `CanExecute`
  is now reactive to current-selection change so bound buttons refresh
  (ADR-0049; VMX-011).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.0 artifact remains MIT-licensed.

### Fixed

- **Lifecycle/dispose concurrency cluster (ADR-0047):** status transitions are
  atomic and dispose-safe behind a per-VM guard; background lifecycle completions
  marshal their terminal emission onto `IDispatcher.Foreground`; a post-dispose
  `IsCurrent` change is a silent no-op; and a throwing `OnConstruct`/`OnDestruct`
  hook rolls `Status` back to the prior settled state (LIFE-008, the new LIFE-014).
- Aligned aggregate/composite/group message-emission order with the Python and
  TypeScript flavors (no spec or conformance dependency on the relative order):
  `AggregateVM6` now emits the hub `PropertyChangedMessage` before the local
  `PropertyChanged` for each component slot (matching arities 1–5); the
  `CompositeVMBase`/`GroupVMBase` indexer setter now auto-constructs the
  replacement child *between* the `Remove` and `Add` collection-changed events
  rather than before the `Remove`.

## [2.6.0] — 2026-06-13

Implements `spec-v2.6.0`. Adds two declarative selection hooks to the
composite builders, plus four ADRs capturing absorption-audit decisions.

### Added

- `CompositeVMBuilder<VM>.Current(Func<IEnumerable<VM>, VM?> selector)` —
  declarative initial-current selector (ADR-0042, COMP-025).
- `CompositeVMBuilder<VM>.OnCurrentChanged(Action<VM?> callback)` —
  synchronous post-change selection callback (ADR-0042, COMP-026).
- Same hooks on the modeled `CompositeVMOfMBuilder<M, VM>`.

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty<T>` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.Current` + `OnCurrentChanged` (behavior change).

### Companion packages

- `VMx.Notifications` — `MinSpecVersion` bumped 2.5.0 → 2.6.0; package
  `Version` unchanged at 1.2.0 (no behavior change; companion follows its
  independent release line per ADR-0009 / ADR-0013).
- `VMx.Extensions.DependencyInjection` — unchanged (Version 2.1.0,
  MinSpecVersion 2.1.0). DI surface has not required updates since v2.1.0.

## [2.5.0] — 2026-06-10

Implements `spec-v2.5.0` (ADR-0037). `VMx.Notifications` companion bumps to
1.2.0 (min spec 2.5.0).

### Fixed

- `ConstructAsync`/`DestructAsync` on an already-Constructed/Destructed
  background VM hung forever and leaked the hub subscription; they now
  short-circuit and also complete when the VM is disposed mid-flight.
- A background construct/destruct racing `Dispose()` could resurrect the VM
  (`Disposed → Constructed`) and publish post-dispose status messages;
  `Disposed` is now terminal in `SetStatus` and the scheduled work
  (spec/02 invariant 3).
- `MessageHub.Send` racing `Dispose` no longer surfaces
  `ObjectDisposedException`.
- `NotificationHub` emits pending snapshots and completes its subject inside
  the lock, closing out-of-order-snapshot and emit-after-dispose windows.
- `FormVM` dispose-during-approve no longer throws in an unobserved task.
- `ObservableList.Clear()` emits `PropertyChanged("Count")` after `Reset`
  when the count changed (spec/21 §3.3).
- Post-2.4.0 maintenance backfill: `AggregateVM6` walk reachability and
  dispose ordering (LIFE-013), `NotificationHub` Post-after-Dispose race,
  and `ServicedObservableCollection.Move` silent corruption.
- The HIER-018 reparent guard compares by reference identity, not
  `Equals` — a `TVM` overriding `Equals` no longer falsely rejects a
  legal reparent (Python/TS already used identity).
- `LinqHelpers.Sample` validates its interval eagerly instead of on first
  enumeration.
- `SearchableState.Filtered`, `ExpandableState.IsExpandedChanged`,
  `NotificationHub.Pending`, and `FormVM.OnApproved` are wrapped with
  `AsObservable()` so callers can no longer downcast to the live subject
  (matches `DerivedProperty.ValueChanged`).
- `FormVM`'s deny path is a no-op after `Dispose()` (previously it
  reverted the model and re-published hub messages on a disposed form),
  and `ApproveAsync()` on a disposed form no longer invokes the
  persister.

### Added

- `FORM-014` conformance coverage: a disposed `FormVM` is inert — approve
  never invokes the persister, deny does not revert (ADR-0038; pins the
  guards shipped earlier in this release).

- `HierarchicalVM.ReparentChild` rejects self- and ancestor-reparenting with
  `InvalidOperationException` instead of silently corrupting the tree
  (HIER-018).
- `NOTIF-017` conformance coverage for the hub's dispose semantics (now
  normative across flavors).

## [2.4.0] — 2026-06-02

Implements spec v2.4.0 — umbrella publication-readiness + Swift flavor
sibling + example-app theming scenario contract + test-coverage backfill
(ADR-0036). Purely additive at the surface level; no behaviour changes
to existing C# APIs.

### Added

- **ThemeVM scenario contract** (example apps): the v2.4.0
  `spec-v2.4.0` cycle defines a normative shape for example-app
  theming (`ThemeModel` + `ThemeVM : ComponentVM<ThemeModel>` +
  per-framework `ThemeAdapter`) built from the existing core
  primitives (`ComponentVM<M>`, `DerivedProperty<TValue>`,
  `RelayCommand`, `MessageHub`). No new core types are introduced;
  the contract is implemented by the Avalonia Notes-Showcase flagship
  under `examples/csharp/avalonia/NotesShowcase/`. See
  `spec/proposals/2026-06-02-theme-vm-scenario.md` + ADR-0036 §2.C.

### Fixed

- **Forwarding decorator coverage backfill.** `ForwardingComponentVM<M>`
  and `ForwardingCompositeVM<VM>` line coverage raised from ~70% and
  ~8% (respectively) to **100%** by adding targeted unit tests for the
  full delegating surface, including selective-override edge cases,
  hub-rebroadcast paths, and dispose-cascade ordering. No production
  code changed; tests only.

### Conformance

- 5 new IDs (`THEME-001..005`); running total goes from 227 to **232**.
  The C# flavor implements `THEME-001..005` as part of the Avalonia
  Notes-Showcase flagship's conformance suite (the contract is
  scenario-level, not a core library addition).

### Min spec version

- 2.4.0 (previously 2.3.0).

## [2.3.0] — 2026-05-31

Implements spec v2.3.0 — builder pattern audit follow-through (ADR-0035).
Purely additive at the surface level. One behaviour change brings
`CompositeVMBuilder<VM>` and `GroupVMBuilder<VM>` into compliance with
the existing spec §3 contract (see Fixed below); callers that were
relying on the previously-lazy validation were already buggy.

### Added

- **`FormVMBuilder<TM>`** (`VMx.Forms`) — fluent immutable builder for
  `FormVM<TM>` with `.Initial(...)` and `.Persister(...)` (or
  `.WithFormPersister(IFormPersister<TM>)`) required, and optional
  `.Hub(...)`, `.Strict(bool)`, `.Snapshotter(...)`. Validates at
  `Build()`. Conformance: `FORM-011..013`. See ADR-0035 §FV1/FV2.
- **`HierarchicalVMBuilder<TModel, TVM>`** (`VMx.Hierarchical`) — fluent
  immutable builder for `HierarchicalVM<TModel, TVM>` with `.Model(...)`,
  `.ChildrenFactory(...)`, `.Services(hub, dispatcher)` required, and
  optional `.Name(...)`, `.Hint(...)`, `.EagerChildren(bool)`. Validates
  at `Build()`. Conformance: `HIER-015..017`. See ADR-0035 §H1/H2/H3.
- New `HierarchicalVMConstructionContext` exposed to children factories.

### Fixed

- `CompositeVMBuilder<VM>.Build()` and `GroupVMBuilder<VM>.Build()` now
  raise `BuilderValidationException` when `Children` is unset, matching
  the spec/10 §3 contract and the TypeScript flavor's existing behaviour.
  Previously these flavors silently accepted a missing `Children` factory
  and raised later at `OnConstruct`. See ADR-0035 §CP1/GR2.

### Conformance

- 7 new IDs (`BLD-005`, `FORM-011..013`, `HIER-015..017`); running total
  goes from 220 to 227. Note: `FORM-011` and `HIER-015` are each split
  into multiple per-missing-field tests, so the test count delta is
  greater than the ID count delta.

### Min spec version

- 2.3.0 (previously 2.2.0).

## [2.2.0] — 2026-05-30

### Added

- `AggregateVM6` and `AggregateVM6.Builder` — sixth-arity heterogeneous
  aggregate. Conformance: `AGG-006`. See ADR-0034.

### Conformance

- 1 new ID (`AGG-006`); running total: 220.

### Min spec version

- 2.2.0 (previously 2.1.0).

## [2.1.0] — 2026-05-28

Implements spec v2.1.0. Purely additive — no breaking changes from v2.0.x.

### Added

- **`HierarchicalVM<TModel, TVM>`** (`VMx.Hierarchical`) — first-class recursive
  tree VM with lazy/eager child loading, depth-first construction, materialized
  path, parent-change and structural-change hub messages.
  `TreeStructureChangedMessage` new message type. (ADR-0028; HIER-001..014)
- **`IDialogService`** + **`NullDialogService`** (`VMx.Dialogs`) — host-side
  contract for modal interactions (file pick, confirm prompt, severity-tagged
  notify) distinct from `INotificationHub`. (ADR-0029; DIA-001..008)
- **`FormVM<TM>`** (`VMx.Forms`) — snapshot/revert edit lifecycle (ORM-agnostic).
  `DenyCommand`, `ApproveCommand`, `OnApproved` event, optional strict mode.
  `FormRevertedMessage` new type. (ADR-0030; FORM-001..010)
- **`NotificationVM`** + **`ConfirmationVM`** (`VMx.Notifications`) — render-side
  VMs with auto-dismiss (60s/300s default), opacity decay, dismiss/approve/reject
  commands. (ADR-0031; NOTIF-011..016)
- **`ServicedObservableCollection<T>`** (`VMx.Collections`) — observable collection
  with hub publication. (ADR-0024; COL-001..004)
- **`ObservableList<T>`** (`VMx.Collections`) — granular per-mutation events
  (ItemAdded/Removed/Replaced/Reset) with batch suppression. (ADR-0026;
  COL-005..009, COL-023)
- **`ObservableDictionary<K1, K2, V>`** (`VMx.Collections`) — composite-key
  observable dictionary with observable Keys1/Keys2 views and hub publication.
  (ADR-0025; COL-010..015, COL-022)
- **`PagedComposition<TVM>`** (`VMx.Collections`) — paging decorator over any
  composition implementing `IPageable`. (ADR-0023; COL-016..021)
- **`IFilterable<T>`** + **`IPageable`** (`VMx.Capabilities`) — two new
  capability micro-interfaces. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command extensions** (`VMx.Commands`) — `Confirm(…)`, `PrecedeWith`,
  `SucceedWith`, `WrapWith` over `ICommand`. (ADR-0027; CMD-008..011)
- **`PropertyValueChangedMessagesFor`** helper (`VMx.Messages`) —
  extension method on `IMessageHub` that filters `PropertyChangedMessage`
  events for a given sender + property name and returns
  `IObservable<TProperty>` snapshots of the property value.
  (ADR-0032; informative)
- **LINQ helpers** (`VMx.Extensions`) — `CartesianProduct`, `Sample`, `Product`
  extension methods. (ADR-0033; C# only)
- `RxDispatcher.Immediate()` — static factory returning a dispatcher with
  `ImmediateScheduler.Instance` on both Foreground and Background. Cross-flavor
  parity with Python `RxDispatcher.immediate()` and TypeScript
  `RxDispatcher.immediate()`.
- **Conformance**: 67 new IDs (total 219).

### Fixed

- `CompositeVMBase<VM>` indexer setter (`this[i] = newItem`) now clears
  `Current` to null when the replaced slot held the current selection,
  mirroring `RemoveAt`. Previously `_current` would silently dangle on
  the no-longer-present old child.
- `AggregateVM1..5.OnConstruct` now disposes the previous slot instance
  before invoking the factory on Reconstruct, so the old VM's hub
  subscriptions and command Subjects are released instead of lingering
  until the hub itself is disposed.
- `SearchableState<TItem>.SearchTerm` setter no longer pushes the new
  value through the debounce/recompute pipeline when it equals the
  current value (spec wording: "emission on a new value").
- `DecoratorCommand.Execute` now wraps the inner `Execute` call in
  try/finally so the `postExecute` callback always runs — a "busy" flag
  set in `preExecute` no longer gets stuck when the inner command
  throws.

### Changed

- `ServiceCollectionExtensions.AddVMx` now captures
  `SynchronizationContext.Current` at the time of the `AddVMx` call,
  rather than lazily at the first `IDispatcher` resolution. This binds
  the default dispatcher to the correct UI thread even when the
  singleton is first resolved on a worker thread. Fall back to
  `RxDispatcher.CreateForCurrentContext()` when no `SynchronizationContext`
  is present at `AddVMx`-time, preserving the legacy console/test path.
- `VMx.Tree.Tree.Walk` / `WalkExpanded` no longer use reflection to
  enumerate aggregate component slots; they pattern-match on a new
  internal `IAggregateSlots` interface implemented by each AggregateVMN.

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`VMx.Capabilities`): 20 opt-in micro-interfaces —
  `ISelectable`, `IDeselectable`, `ISelectionTogglable`, `IExpandable`,
  `ICollapsible`, `IExpansionTogglable`, `ISearchable`, `IClosable`,
  `IApprovable`, `ICancelable`, `INewCreatable`, `IDeletable`,
  `IUpdatable`, `ISavable`, `ICurrentDeletable`, `ICurrentUpdatable`,
  `IManagable`, `IConstructable`, `IDestructable`, `IReconstructable`
  (see `src/VMx/Capabilities/`).
- **Helpers** (`VMx.Capabilities`): `SearchableState<TItem>` (trailing-edge
  debounce, configurable scheduler), `ExpandableState`.
- **Derived properties** (`VMx.Properties`): `DerivedProperty<TValue>` plus
  strongly-typed `From<T1..T5,TValue>` overloads and an untyped `FromMany`
  for arbitrary N.
- **Commands**: `ConfirmationDecoratorCommand` + the abstract `DecoratorCommand`
  base, `MakeConfirm` helper, `ModeledCrudCommands<M, VM>` for the CRUD trio.
- **Null-object services** (per ADR-0017): `NullMessageHub`, `NullDispatcher`,
  `NullLocalizer`, plus `NullNotificationHub` (in the notifications package).
- **Localization** (`VMx.Localization`): `ILocalizer` interface and
  `NullLocalizer` (identity translator).
- **Notifications sub-package** (`VMx.Notifications`, separate NuGet package,
  versioned independently per ADR-0013): `Notification`, `NotificationType`,
  `NotificationReaction`, `INotificationHub` + `NotificationHub` reference
  impl + `NullNotificationHub`.
- **Tree utilities**: `Tree.WalkExpanded(root)` variant that descends only
  into expanded composites.
- **Conformance**: 77 new IDs added (total 152).

### Internal
- `BuilderValidationException.Require([NotNull])` rolled out to the new
  v2.0 builders (CRUD, expandable, searchable, derived) for consistent
  null-check shapes.
- All v2.0 helpers (`SearchableState`, `ModeledCrudCommands`,
  `DerivedProperty`, `ExpandableState`) implement `IDisposable` and are
  idempotent.

## [1.2.0] — 2026-05-23

### Added
- Non-modeled `ComponentVM` class + `ComponentVMBuilder` for parity with the
  Python and TypeScript flavors. Existing `ComponentVM<M>` continues to ship
  alongside it (additive change, no consumer impact).
- `BuilderValidationException.Require([NotNull] object?, string)` static helper.
  All 41 in-place null-check throws across the aggregate, composite, group, and
  component builders are migrated to call it; the `[NotNull]` annotation lets
  the C# flow analyser narrow the field as non-null after a successful call.
- `System.Diagnostics.CodeAnalysis.NotNullAttribute` polyfill for the
  netstandard2.0 target (existing `IsExternalInit` polyfill pattern).

### Removed
- `ComponentVMBuilder<M>.AsyncSelection(bool)` setter — the parameter was stored
  on the builder but never forwarded to the constructed `ComponentVM<M>` (only
  `CompositeVMBuilder<…>.AsyncSelection` is honoured at runtime, and that setter
  is unchanged). No test referenced the component-level setter.

### Internal
- Comment polish on `ComponentVMBase.IsCurrent` idempotent-set guard,
  `LifecycleTransitionValidator` `Lazy<T>` thread-safety, and
  `Directory.Packages.props` central transitive pinning.

## [1.1.0] — 2026-05-23

### Added
- Implements spec-v1.1.0 on top of the v1.0.0 surface.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `.AutoConstructOnAdd(bool)` builder option. When `true`, a child added after the container reaches `Constructed` is automatically constructed before the `CollectionChanged(Add)` event fires.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `BatchUpdate()` method returns an `IDisposable` that suppresses per-mutation `CollectionChanged` events. The outermost `Dispose` emits a single `CollectionChanged(Reset)` event iff any mutations occurred.
- New `VMx.Tree` namespace with `Tree.Walk(root)` (lazy DFS pre-order) and `Tree.Find(root, predicate)` (short-circuiting first-match).
- Async lifecycle wrappers `ConstructAsync()` / `DestructAsync()` / `ReconstructAsync()` on `IComponentVM` (.NET TAP convention; spec-neutral — see ADR-0008).
- New conformance IDs: COMP-012, COMP-013, GRP-005, GRP-006, UTIL-001, UTIL-002, UTIL-003 (89 conformance test methods; 75 catalog IDs covered).

## [1.0.0] — 2026-05-22

### Added
- Full implementation of spec-v1.0.0:
  - Lifecycle: `ConstructionStatus` + `StatusTransitionException` + transition validator
  - Messages: `IMessage` hierarchy + `PropertyChangedMessage` + `ConstructionStatusChangedMessage`
  - Services: `IMessageHub`/`MessageHub` + `IDispatcher`/`RxDispatcher`
  - Commands: `RelayCommand` + `RelayCommand<T>` with reactive triggers and immutable builders
  - Components: `ComponentVM<M>` + `ReadonlyComponentVM<M>` with full lifecycle, modeled hint, and built-in commands
  - Composites: `CompositeVM<VM>` + `CompositeVM<M, VM>` with selection contract, IList + INotifyCollectionChanged, async-selection dispatch
  - Groups: `GroupVM<VM>` (children-as-peers; retains SelectCommand/DeselectCommand for self-selection in parent)
  - Aggregates: `AggregateVM1`..`AggregateVM5` fixed-arity tuples with parallel construction
  - Forwarding: `ForwardingComponentVM<M>` + `ForwardingCompositeVM<VM>` decorators
  - Background option (`Background(true)`) dispatches construct/destruct on `IDispatcher.Background`
  - Optional DI companion package `VMx.Extensions.DependencyInjection` with `AddVMx()`
- 68 conformance IDs covered (82 test methods) — LIFE-001..013, HUB-001..007, PROP-001..004, CMD-001..007, CVM-001..006, COMP-001..011, GRP-001..004, AGG-001..005, FWD-001..003, BLD-001..004, THR-001..004 — all pass.
- 194 unit tests across all modules — all pass.
- Multi-target `netstandard2.0;net8.0`. Test runner targets `net9.0`.
- Examples: `examples/csharp/HelloVMx/` (console) and `examples/csharp/WpfTodoApp/` (WPF binding, Windows-only build).
- Getting-started tutorial at `docs/getting-started/csharp.md`.
