# Changelog

All notable changes to the C# flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`VMx.Capabilities`): 20 opt-in micro-interfaces
  (`ISearchable`, `IExpandable`, `ICollapsible`, `IExpansionTogglable`,
  `IDirty`, `IDisposable`, `IBusy`, `IValidatable`, etc.).
- **Helpers** (`VMx.Capabilities`): `SearchableState<TItem>` (trailing-edge
  debounce, configurable scheduler), `ExpandableState`.
- **Derived properties** (`VMx.Properties`): `DerivedProperty<TValue>` plus
  strongly-typed `From<T1..T5,TValue>` overloads and an untyped `FromMany`
  for arbitrary N.
- **Commands**: `ConfirmationDecoratorCommand`, `LoggingDecoratorCommand`,
  `MakeConfirm` helper, `ModeledCrudCommands<M, VM>` for the CRUD trio.
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
