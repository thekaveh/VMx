# Changelog — @thekaveh/vmx (TypeScript)

All notable changes to the TypeScript flavor of vmx are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## 2.4.0 — 2026-06-02

Implements spec v2.4.0 — umbrella publication-readiness + Swift flavor
sibling + example-app theming scenario contract + test-coverage backfill
(ADR-0036). One published-name change (see Changed below); no behaviour
changes to existing TS APIs.

### Changed

- **npm package renamed from `vmx` to `@thekaveh/vmx`** (the unscoped
  `vmx` name was unavailable on the public npm registry). Install
  command becomes `npm install @thekaveh/vmx rxjs`; imports become
  `import { ... } from "@thekaveh/vmx"`. The opt-in notifications
  sub-path is now `@thekaveh/vmx/notifications`. Source-compatible: no
  symbol changes. See ADR-0036 §2.A.

### Added

- **ThemeVM scenario contract** (example apps): the v2.4.0
  `spec-v2.4.0` cycle defines a normative shape for example-app
  theming (`ThemeModel` + `ThemeVM extends ComponentVMOf<ThemeModel>`
  + per-framework `ThemeAdapter`) built from the existing core
  primitives (`ComponentVMOf<M>`, `DerivedProperty<TValue>`,
  `RelayCommand`, `MessageHub`). No new core types are introduced;
  the contract is implemented by the React Notes-Showcase flagship
  under `examples/typescript/react/notes-showcase/`. See
  `spec/proposals/2026-06-02-theme-vm-scenario.md` + ADR-0036 §2.C.

### Fixed

- **Example-app edge-case coverage backfill.** The React Notes-Showcase
  flagship gained dedicated tests for the filter / search / paging
  interaction matrix, capability-aware action-bar gating, and FormVM
  approve/deny edge cases that were previously implicit. No production
  code changed; tests only.

### Conformance

- 5 new IDs (`THEME-001..005`); running total goes from 227 to **232**.
  The TS flavor implements `THEME-001..005` as part of the React
  Notes-Showcase flagship's conformance suite (the contract is
  scenario-level, not a core library addition).

### Min spec version

- 2.4.0 (previously 2.3.0).

## 2.3.0 — 2026-05-31

Implements spec v2.3.0 — builder pattern audit follow-through (ADR-0035).
Purely additive at the surface level. The C# / Python flavors gain
validation parity with TS's existing Children-at-`build()` behaviour.

### Fixed

- **D1 — Browser-safe dist.** `src/lifecycle/transitionValidator.ts` no
  longer imports `node:fs` / `node:path` / `node:url` at module load. The
  `lifecycle-transitions.json` fixture is now consumed via a static
  TypeScript JSON import and bundled into both ESM and CJS dist artifacts
  by tsup/esbuild. Browsers using Vite, Webpack, esbuild, Rollup, Bun, and
  Tauri webviews can load `vmx` directly with no node-builtin stubs.

### Changed

- **D2 — `rxjs` moved to `peerDependencies`.** Previously declared as a
  hard dependency; consumers using pnpm strict isolation (default for new
  Vite/SvelteKit projects) hit resolution friction when vendoring VMx.
  Public install command is now `npm install vmx rxjs`. `rxjs` remains in
  `devDependencies` for local test runs. `peerDependenciesMeta.rxjs.optional`
  is `false` (required).

### Added

- **`FormVMBuilder<TM>`** (`vmx` — `forms/`) — fluent immutable builder for
  `FormVM<TM>` with `.initial(...)` and `.persister(...)` required, and
  optional `.hub(...)`, `.strict(boolean)`, `.snapshotter(...)`. Validates
  at `build()`. Conformance: `FORM-011..013`. See ADR-0035 §FV1/FV2.
- **`HierarchicalVMBuilder<TModel, TVM>`** (`vmx` — `hierarchical/`) —
  fluent immutable builder for `HierarchicalVM<TModel, TVM>` with
  `.model(...)`, `.childrenFactory(...)`, `.services(hub, dispatcher)`
  required, and optional `.name(...)`, `.hint(...)`,
  `.eagerChildren(boolean)`. Adds `.withDefaultServices()` Wither for
  opt-in implicit defaults. Validates at `build()`. Conformance:
  `HIER-015..017`. See ADR-0035 §H1/H2/H3.
- **`HierarchicalVMConstructionContext`** — new context type passed to
  children-factory callbacks for the hierarchical builder.
- **`withNullServices()`** Wither extension on `ComponentVMBuilder` and
  friends — chainable convenience that wires `NullMessageHub.INSTANCE`
  + `NullDispatcher.INSTANCE` in one call, for parity with the C#
  `WithNullServices()` extension. See ADR-0035 §SV1.
- `tests/browser-build/smoke.test.ts` — JSDOM environment smoke test that
  loads the public surface and instantiates a `ComponentVMOf` to catch
  future regressions of the browser-safety contract (companion to D1).
- README §3.5 "Browser usage" documenting bundler compatibility and the
  rxjs peer-dependency install command (companion to D2).

### Conformance

- 7 new IDs (`BLD-005`, `FORM-011..013`, `HIER-015..017`); running total
  goes from 220 to 227.

### Min spec version

- 2.3.0 (previously 2.2.0).

## 2.2.0 — 2026-05-30

### Added

- `AggregateVM6` — sixth-arity heterogeneous aggregate.
  Conformance: `AGG-006`. See ADR-0034.

### Conformance

- 1 new ID (`AGG-006`); running total: 220.

### Min spec version

- 2.2.0 (previously 2.1.0).

## [2.1.0] — 2026-05-28

Implements spec v2.1.0. Purely additive — no breaking changes from v2.0.x.

### Added

- **`HierarchicalVM<TModel, TVM>`** (`vmx` — `hierarchical/`) — first-class
  recursive tree VM with lazy/eager child loading, depth-first construction,
  materialized path, parent-change and structural-change hub messages.
  `TreeStructureChangedMessage` new type. (ADR-0028; HIER-001..014)
- **`IDialogService`** + **`NullDialogService`** (`vmx` — `dialogs/`) —
  host-side contract for modal interactions (file pick, confirm prompt,
  severity-tagged notify) distinct from `INotificationHub`. (ADR-0029;
  DIA-001..008)
- **`FormVM<TM>`** (`vmx` — `forms/`) — snapshot/revert edit lifecycle
  (ORM-agnostic). `denyCommand`, `approveCommand`, `onApproved` event,
  optional strict mode. `FormRevertedMessage` new type. (ADR-0030;
  FORM-001..010)
- **`NotificationVM`** + **`ConfirmationVM`** (`vmx/notifications`) —
  render-side VMs with auto-dismiss (60s/300s default), opacity decay,
  dismiss/approve/reject commands. (ADR-0031; NOTIF-011..016)
- **`ServicedObservableCollection<T>`** (`vmx` — `collections/`) —
  observable collection with hub publication. (ADR-0024; COL-001..004)
- **`ObservableList<T>`** (`vmx` — `collections/`) — granular per-mutation
  events (itemAdded/Removed/Replaced/Reset) with batch suppression.
  (ADR-0026; COL-005..009, COL-023)
- **`ObservableDictionary<K1, K2, V>`** (`vmx` — `collections/`) —
  composite-key observable dictionary with observable keys1/keys2 views and
  hub publication. (ADR-0025; COL-010..015, COL-022)
- **`PagedComposition<TVM>`** (`vmx` — `collections/`) — paging decorator
  over any composition implementing `IPageable`. (ADR-0023; COL-016..021)
- **`IFilterable<T>`** + **`IPageable`** (`vmx` — `capabilities/`) — two new
  capability interfaces. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command helpers** (`vmx` — `commands/`) — `confirm(…)`,
  `precedeWith`, `succeedWith`, `wrapWith` extension helpers over commands.
  (ADR-0027; CMD-008..011)
- **`propertyValueChangedMessagesFor`** helper (`vmx` — `messages/`) —
  function that filters `PropertyChangedMessage` events for a given
  sender + property name and returns an observable stream of the
  property's value snapshots. (ADR-0032; informative)
- Re-exports of `IBatchable` (collections) and `IParentVM` (components)
  from the main `vmx` barrel for parity with the rest of the public
  surface — previously only reachable via deep sub-path imports.
- `tree/index.ts` re-exports `walkExpanded` alongside `walk` and `find`
  for sub-index completeness.
- **Conformance**: 67 new IDs (total 219).

### Fixed

- `CompositeVMBase.setAt` now clears `current` to null when the
  replaced slot held the current selection, mirroring `removeAt`.
- `AggregateVM1..5._onConstruct` now disposes the previous slot
  instance before invoking the factory on Reconstruct, so the old
  VM's hub subscriptions and command Subjects are released instead of
  lingering until the hub itself is disposed. (Parity with the C# fix.)
- `SearchableState.searchTerm` setter no longer pushes the new value
  through the debounce/recompute pipeline when it equals the current
  value (spec wording: "emission on a new value").
- `DecoratorCommand.execute` now wraps the inner `execute` call in
  try/finally so the `postExecute` callback always runs — a "busy"
  flag set in `preExecute` no longer gets stuck when the inner
  command throws.
- `AggregateVM4Builder.build()` / `AggregateVM5Builder.build()` now
  throw per-field `BuilderValidationError("componentN")` for the first
  missing slot, matching the arity-1/2/3 builders. Previously they
  collapsed into a single generic `"components"` error, so consumers
  could not programmatically distinguish which slot was missing.

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`vmx`): 20 opt-in micro-interfaces —
  `ISelectable`, `IDeselectable`, `ISelectionTogglable`, `IExpandable`,
  `ICollapsible`, `IExpansionTogglable`, `ISearchable`, `IClosable`,
  `IApprovable`, `ICancelable`, `INewCreatable`, `IDeletable`,
  `IUpdatable`, `ISavable`, `ICurrentDeletable`, `ICurrentUpdatable`,
  `IManagable`, `IConstructable`, `IDestructable`, `IReconstructable`
  (see `src/capabilities/registry.ts`).
- **Helpers** (`vmx`): `SearchableState<TItem>` (real `debounceTime`,
  trailing-edge), `ExpandableState`.
- **Derived properties** (`vmx`): `DerivedProperty<TValue>` plus a
  `fromSources(sources, transform, opts?)` factory for N-source
  computed values, value-equality guard via `Object.is`, optional
  write-back.
- **Commands**: `ConfirmationDecoratorCommand` + the abstract
  `DecoratorCommand` base, `makeConfirm` helper, `ModeledCrudCommands<M, VM>`
  (M is a phantom type parameter mirroring the spec contract — see ADR-0016).
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
