# Changelog — vmx (TypeScript)

All notable changes to the TypeScript flavor of vmx are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`vmx`): 20 opt-in micro-interfaces (`ISearchable`,
  `IExpandable`, `ICollapsible`, `IExpansionTogglable`, `IDirty`,
  `IDisposable`, `IBusy`, `IValidatable`, etc.).
- **Helpers** (`vmx`): `SearchableState<TItem>` (real `debounceTime`,
  trailing-edge), `ExpandableState`.
- **Derived properties** (`vmx`): `DerivedProperty<TValue>` plus a
  `fromSources(sources, transform, opts?)` factory for N-source
  computed values with `distinctUntilChanged` + optional write-back.
- **Commands**: `ConfirmationDecoratorCommand`, `LoggingDecoratorCommand`,
  `makeConfirm` helper, `ModeledCrudCommands<M, VM>` (M is a phantom
  type parameter mirroring the spec contract — see ADR-0016).
- **Null-object services** (per ADR-0017): `NullMessageHub`,
  `NullDispatcher`, `NullLocalizer`, plus `NullNotificationHub` (in the
  notifications package).
- **Localization** (`vmx`): `ILocalizer` interface and `NullLocalizer`
  (identity translator).
- **Notifications sub-package** (`vmx` namespace `notifications/`,
  shipped in-package but tree-shakable): `Notification`, `NotificationType`,
  `NotificationReaction`, `INotificationHub` + `NotificationHub` reference
  impl + `NullNotificationHub`.
- **Tree utilities**: `walkExpanded(root)` variant that descends only into
  expanded composites.
- **Conformance**: 77 new IDs added (total 152).

### Changed (breaking)
- `ModeledCrudCommands<VM>` is now `ModeledCrudCommands<M, VM>` (phantom
  `M`). Update callsites from `new ModeledCrudCommands<MyVM>({...})` to
  `new ModeledCrudCommands<MyModel, MyVM>({...})`.
- `deriveFromSources(sources, transform, opts)` is renamed `fromSources`
  to match the ADR-0006 idiom mapping (`from_sources` in Python).
  Update imports.

## [1.2.0] — 2026-05-23

### Added
- `ConstructionStatusChangedMessage.sender` getter — alias of `senderObject`,
  matching the typed `sender` field on the C# and Python flavors.
- `scripts/check-version-sync.mjs` enforces `package.json.version` ↔
  `src/version.ts.__version__` agreement and runs as part of `prebuild` and
  `prepack` so a release that forgets to update one side fails fast.

### Fixed
- `scripts/sync-fixtures.mjs` now reports a clear error if `spec/fixtures/`
  is missing rather than failing inside `readdirSync` with an opaque ENOENT.

### Internal
- JSDoc note on `selectNextCommand` / `selectPreviousCommand` explaining the
  hard-coded `false` predicate semantics on orphan leaves (CVM-005).
- Module docstring on `version.ts` documenting the manual-sync contract that
  the new `check-version-sync.mjs` enforces.

## [1.1.0] — 2026-05-23

Initial release. Implements all 75 conformance IDs from spec v1.1.0 with full
parity against the C# and Python flavors.

### Added

- `ComponentVM`, `ComponentVMOf<M>`, `ReadonlyComponentVMOf<M>` — leaf viewmodels.
- `CompositeVM<VM>`, `CompositeVMOf<M, VM>` — ordered collection + current selection.
- `GroupVM<VM>` — ordered collection without selection.
- `AggregateVM1..5` — fixed-arity named-slot aggregates.
- `ForwardingComponentVM<M>`, `ForwardingCompositeVM<VM>` — forwarding decorators.
- `RelayCommand`, `RelayCommandOf<T>` — executable commands with reactive `canExecute`.
- `MessageHub` — rxjs `Subject`-backed pub/sub hub with per-subscriber exception swallowing.
- `RxDispatcher` — foreground/background scheduler pair; `immediate()` uses `queueScheduler` for both.
- `ConstructionStatus` — 5-state lifecycle enum (`Disposed`, `Destructing`, `Destructed`, `Constructing`, `Constructed`).
- `StatusTransitionError` — raised on illegal lifecycle transitions.
- `PropertyChangedMessage`, `ConstructionStatusChangedMessage` — immutable message types.
- `BatchUpdateHandle` — ref-counted batch with `dispose()` / TC39 `[Symbol.dispose]()`.
- `walk(root)`, `find(root, predicate)` — DFS pre-order tree utilities.
- Fluent immutable builders for every public type.
- Dual ESM + CJS output via tsup; TypeScript declarations bundled.
