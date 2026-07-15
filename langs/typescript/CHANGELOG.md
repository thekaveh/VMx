# Changelog — @thekaveh/vmx (TypeScript)

All notable changes to the TypeScript flavor of vmx are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.23.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Fixed

- Terminal disposal now attempts every child and all base teardown before
  rethrowing the first failure, so one faulty child or subclass hook cannot
  strand siblings, commands, resources, or streams (LIFE-013, ADR-0108).

## [3.22.0] — 2026-07-14

Implements `spec-v3.21.0` with 395/395 library conformance IDs covered.

### Changed

- Components now have one authoritative owning parent. Mutable composite and
  group attachment transfers ownership atomically; fixed aggregate slots reject
  transfers, duplicate identities, and ownership cycles (COMP-038..041,
  ADR-0107).

### Fixed

- Form reset publication now defers model edits requested by validation
  observers until `onApproved` has observed the pristine committed state.
- Hierarchy cache invalidation now detaches discarded children so retained
  nodes have a truthful parent and can be attached again.
- A newer token-page refresh now supersedes an older in-flight load, preventing
  stale results from being appended after the refreshed first page.
- `FormVM` now completes admitted synchronous assignment, reset, revert, and
  error-publication work before reentrant disposal tears down its RxJS signals.
- `NotificationHub` serializes reentrant pending snapshots in mutation order
  and gives late subscribers one current snapshot without queued history.

## [3.21.1] — 2026-07-14

Implements `spec-v3.20.1` with 391/391 library conformance IDs covered.

### Fixed

- `AsyncRelayCommand.executeAsync` now detaches an external `AbortSignal`
  listener after success, fault, or disposal-driven cancellation.
- `HierarchicalVM.addChild` rejects cycles and atomically transfers an attached
  child (HIER-018, ADR-0105).
- `ForwardingCompositeVM` delegates hub, parent selection, snapshots,
  membership subscriptions, and moves in addition to the existing surface.

## [3.21.0] — 2026-07-12

Continues to implement `spec-v3.20.0` with 391/391 library conformance IDs.

### Added

- `@thekaveh/vmx/conformance` provides the versioned consumer adapter schema,
  strict validation, ordered factory runner, structural state and exact message
  assertions, path-addressed diagnostics, and deterministic teardown (ADR-0102).
- `adaptCommandTruthTableFixture` proves the runner against every unchanged VMx
  command truth-table row without replacing CMD-007.

### Changed

- Isolated ESM, CommonJS, and declaration outputs keep Ajv and runner APIs out
  of the root package entry.
- Release CI validates an explicit package-content allowlist and clean ESM,
  CommonJS, NodeNext, notifications, and conformance consumers before publish;
  it supports a one-time token bootstrap followed by npm trusted publishing,
  public-registry polling, provenance verification, and GitHub release notes.

## [3.20.0] — 2026-07-12

Implements `spec-v3.20.0` and keeps TypeScript at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncResourceVM<T>` models one cancellable async value with immutable
  Idle/Loading/Ready/Error state and load, reload, and cancel commands
  (`ARES-001..011`, ADR-0100).

### Changed

- Latest-start-wins admission rejects stale completion, optional retention
  keeps the accepted value visible, and acquisition-based cleanup releases
  discarded, replaced, stale, and terminal values exactly once.

## [3.19.0] — 2026-07-12

Implements `spec-v3.19.0` and keeps TypeScript at full library parity: 380/380
conformance IDs covered.

### Added

- `SearchableStateOptions<T>.sourceChanges` refreshes the current term after
  source mutations (`SRCH-001..007`, ADR-0099).

### Changed

- Source pulses bypass without resetting term debounce, preserve upstream batch
  boundaries and value-equal emissions, isolate signal failure/completion, and
  cancel only the helper-owned subscription on disposal. The VMX-093
  snapshot-only warning is removed.

## [3.18.0] — 2026-07-12

Implements `spec-v3.18.0` and keeps TypeScript at full library parity: 373/373
conformance IDs covered.

### Added

- `ObservableMembershipSource<T>` and `AggregateChangeStream<T>` follow
  committed membership in composites, groups, and both serviced collection
  families while reporting `Initial`, `Membership`, `Item`, or `Batch`
  provenance (`AGCH-001..010`, ADR-0098).
- `forComponents` selects standard component property changes; the general
  selector can observe nested local state.

### Changed

- Duplicate occurrences of the same object identity share one selected
  subscription; distinct identities each have their own. Explicit nested
  batches coalesce aggregate output, and idempotent disposal detaches only
  aggregate-owned subscriptions without owning source items.

## [3.17.0] — 2026-07-12

Implements `spec-v3.17.0` and keeps TypeScript at full library parity: 363/363
conformance IDs covered.

### Added

- `KeyedServicedObservableCollection<TKey, TItem>` adds captured-key `get`,
  `has`, `upsert`, and `delete` operations while retaining ordered serviced
  collection and array conveniences (`COL-056..064`, ADR-0097).
- Duplicate-key validation and final-result preflight make `splice`,
  `replaceAll`, and indexed rekeying atomic.

### Changed

- Key lookup and present-key upsert use the captured-key index; item lifecycle
  remains caller-owned and external transactions still defer only hub delivery.

## [3.16.0] — 2026-07-12

Implements `spec-v3.16.0` and keeps TypeScript at full library parity: 354/354
conformance IDs covered.

### Added

- `ServicedObservableCollection<T>` adds first-match `remove`, strict
  `removeAt`, named `replace`, snapshot-based `replaceAll`, and atomic `move`
  while retaining `setAt`, splice, and array conveniences (`COL-048..055`,
  ADR-0096).
- Collection-change messages retain `index` and add precise `oldIndex` /
  `newIndex` positions, including one Move delivered locally before the
  optional hub sees the final state.

### Changed

- Empty clear, empty-to-empty replacement, and same-index move no-ops are
  notification-free; serviced mutations never acquire item lifecycle ownership.

## [3.15.0] — 2026-07-11

Implements `spec-v3.15.0` and keeps TypeScript at full library parity: 346/346
conformance IDs covered.

### Added

- `subscribeValue(...)` observes selected state from one fixed VM through its
  hub, supports `Object.is` or custom equality and optional immediate delivery,
  reports current/previous values, and returns an RxJS `Subscription` teardown
  handle. Re-entrant ordering, batching, disposal, and subscriber failure
  behavior follow the existing hub contract (`SUBV-001..004`, ADR-0095).

## [3.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps TypeScript at full library parity: 342/342
conformance IDs covered.

### Added

- `isPropertyChanged`, `isCollectionChanged`, and
  `isConstructionStatusChanged` classify existing raw messages with exact
  optional constraints and filter-safe type narrowing. A generic property sender
  is inferred only from a checked sender; collection payloads remain `unknown`
  because source identity cannot prove the independently constructed item type.
  Explicitly present `undefined` constraints compare exactly. The predicates
  compose with `Array.filter`, RxJS `filter`, and the existing higher-level
  message helpers without changing message semantics (ADR-0094).

## [3.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps TypeScript at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republishModel()`, which retains model and hint state, skips assignment,
  hinter, and callback work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [3.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps TypeScript at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVM.setModel` now uses its configured/default structural equality to
  suppress a no-op candidate, then publishes exactly one model
  `PropertyChangedMessage` after model, validation, and approve-command state
  settle (`FORM-030`, ADR-0092).
- Compatibility: unequal edits are now visible on the configured hub, while a
  distinct equality-equal candidate is retained silently instead of replacing
  the live model and rerunning validators.

## [3.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps TypeScript at full library parity: 340/340
conformance IDs covered.

### Changed

- Modeled component and `FormVM.setModel` assignment return before equality,
  retained-state, hinting, validation, command-state, callback, or notification
  work after disposal (`DISP-014`, ADR-0091).

## [3.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps TypeScript at full library parity: 339/339
conformance IDs covered.

### Added

- `IComponentVM.hub` exposes the injected shared hub read-only.
- `ComponentVMBase.own(...)` registers functions, disposables, or subscriptions
  for exactly-once LIFO terminal cleanup (`DISP-007..013`).

## [3.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps TypeScript at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList.replaceAll(...)` snapshots iterable input and emits one Reset
  plus cardinality-dependent `Count` (`COL-040..047`).

## [3.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps TypeScript at full library parity: 324/324
conformance IDs covered.

### Added

- `attachMany(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [3.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps TypeScript at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `resetOnApproved(...)` for declarative post-persist reset,
  including independent snapshots, revalidation, deterministic race semantics,
  and existing approval error routing (`FORM-024..029`).

## [3.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps TypeScript at full library parity: 310/310
conformance IDs covered.

### Added

- `raiseCanExecuteChanged()` on `RelayCommand`, `RelayCommandOf`, and
  `AsyncRelayCommand`, including exact live, repeated, trigger-additive,
  in-flight, and post-dispose behavior (`CMD-014..019`).

### Fixed

- Default `FormVM` snapshot failures now name the construction, approve, or
  deny/revert phase; safely identify the first failing top-level field when
  possible; preserve the native error as `cause`; and point to the paired
  `snapshotter`/`equals` escape hatch. Custom snapshotter errors remain
  unchanged (#102).

## [3.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps TypeScript at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `IVmCollection<VM>` and selection-specific
  `ISelectableVmCollection<VM>` capabilities.
- Atomic identity-preserving `move(fromIndex, toIndex)` and a `"move"`
  collection event (`COL-032..039`).
- The React collection adapter now accepts both groups and composites without
  casts.

## [3.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps TypeScript at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

## [3.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps TypeScript at full library parity: 290/290
conformance IDs covered.

### Added

- Protected `_notifyPropertyChanged` for emitting one hub
  `PropertyChangedMessage` followed by one local property-change notification
  (`CVM-007..009`).

### Changed

- Component, modeled-component, composite, aggregate, and flagship Notes
  Showcase setters now use the shared helper after equality checks and
  assignment.

## [3.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps TypeScript at full library parity: 287/287
conformance IDs covered.

### Added

- `ITransactionalMessageHub` and `hub.batch(callback)` for nested, lossless
  FIFO transactions (`HUB-008..013`).
- Iterative re-entrant delivery and a development publish-cycle diagnostic
  that reports involved message types.

### Changed

- `NullMessageHub` executes transaction callbacks while continuing to publish
  nothing.

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps TypeScript at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.
- Pinned common options-factory conformance (`BLD-006`) and group-child
  non-selection semantics (`GRP-011`).

### Fixed

- `AsyncRelayCommand` is now inert after disposal, and fire-and-forget
  cancellation no longer emits on `errors` when `throwOnCancel()` is set.
- `AsyncRelayCommand` no longer suppresses non-cancellation task faults merely
  because `cancel()` was requested.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes.
- Group children no longer report enabled child selection into a group.
- Removed the ineffective `MessageHub` subscriber-error diagnostic constructor
  hook; RxJS reports subscriber throws through `config.onUnhandledError`.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** — a breaking release that hardens the
lifecycle/dispose concurrency path and reconciles the public surface across
flavors. Implements `spec-v3.0.0`. See ADRs 0047–0058 and
`docs/audit/2026-06-27-vmx-merged-critique.md`.

### Added

- Positional-options construction for the common VMs — a static `create(options)`
  factory alongside the unchanged fluent builders, taking an options object:
  `ComponentVM.create({ … })`, `ComponentVMOf.create({ … })`,
  `CompositeVM.create({ … })`, `GroupVM.create({ … })` (with exported
  `ComponentVMOptions` / `ComponentVMOfOptions<M>` / `CompositeVMOptions<VM>` /
  `GroupVMOptions<VM>` types). Delegates to the builder, so required-field
  validation (`BuilderValidationError`) and the resulting VM are identical to the
  fluent path (ADR-0055; VMX-020).
- `AsyncRelayCommand` — an additive async command that flows an `AbortSignal` into
  a long-running task and adds a `cancel()` method, closing the cancellation gap
  the synchronous `RelayCommand` had. Cancellation is non-throwing to the caller by
  default with an opt-in throwing mode; fire-and-forget task faults route to an
  `errors` observable. `RelayCommand` is unchanged (ADR-0056; CMD-012; VMX-052).
- `FormVM` surfaces approve-path persister failures on a new `approveErrors`
  observable instead of swallowing them; `isDirty` uses an injectable structural
  equality (the default is a deep-equal, not `JSON.stringify`) and the default
  snapshot is a `structuredClone` deep value-copy (ADR-0048; FORM-015).

### Changed

- **BREAKING (v3.0.0):** the untyped `senderObject` field is **renamed to the
  canonical `sender`** on every message — the base `IMessage` and
  `ConstructionStatusChangedMessage`, `CollectionChangedMessage`,
  `PropertyChangedMessage`, `TreeStructureChangedMessage`, `FormRevertedMessage`.
  This restores ADR-0006 cross-flavor parity with the `sender`/`Sender` field
  documented by C#/Python/Swift (ADR-0054, VMX-016/083). The base
  `IMessage.sender` is typed `unknown`; `ITypedMessage<TSender>` /
  `PropertyChangedMessage<TSender>` narrow it to `TSender`. Migration: replace
  `msg.senderObject` with `msg.sender` (identical instance, now typed).
- **BREAKING:** `ConfirmationDecoratorCommand.execute()` (synchronous
  fire-and-forget) now surfaces a rejecting `confirm` delegate or a throwing inner
  command on a new `errors` observable instead of swallowing them; the awaitable
  `executeAsync()` keeps its throw behavior (ADR-0049; CMDD-010).
  `ModeledCrudCommands` update/delete `canExecute` is now reactive to
  current-selection change so bound buttons refresh (ADR-0049; VMX-011).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.0 artifact remains MIT-licensed.

### Fixed

- **Lifecycle/dispose concurrency cluster (ADR-0047):** status transitions are
  atomic and dispose-safe behind a per-VM guard; background lifecycle completions
  marshal their terminal emission onto the foreground dispatcher; a post-dispose
  `isCurrent` change is a silent no-op; and a throwing `onConstruct`/`onDestruct`
  hook rolls `status` back to the prior settled state (LIFE-008, the new LIFE-014).

## [2.6.0] — 2026-06-13

Implements `spec-v2.6.0`. Adds two declarative selection hooks to the
composite builders, plus four ADRs capturing absorption-audit decisions.

### Added

- `CompositeVMBuilder<VM>.current(selector)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder<VM>.onCurrentChanged(callback)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).
- Same hooks on the modeled `CompositeVMOfBuilder<M, VM>`.

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty<T>` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `onCurrentChanged` (behavior change).

## [2.5.0] — 2026-06-10

Implements `spec-v2.5.0` (ADR-0037).

### Changed

- **Hub `PropertyChangedMessage` names are camelCase everywhere** per the TS
  idiom (spec/04 §4, ADR-0037): `"model"`, `"modeledHint"`, `"current"`,
  `"component1".."component6"` — previously these emitted PascalCase while
  `FormVM`/`HierarchicalVM` emitted camelCase. Subscribers filtering on
  `"Model"`, `"Current"`, `"IsCurrent"`, or `"ComponentN"` must update
  their strings.
- `NullDialogService` now has a private constructor — consume the
  `INSTANCE` singleton, matching every other null variant and C#.

### Fixed

- `FormVM`'s `approveCommand` and `ConfirmationDecoratorCommand.execute()`
  no longer turn a rejecting persister/confirm delegate into a fatal
  unhandled rejection on Node ≥ 15.
- `CompositeVMBase.clear()` routes through the current-selection setter; the
  old current child no longer keeps `isCurrent === true` with no
  notification.
- `PagedComposition` subscribes `itemReplaced`; `replace()` on the current
  page refreshes `items`.
- `ObservableList.clear()` emits `propertyChanged("Count")` after `reset`
  when the count changed (spec/21 §3.3).
- `GroupVM` construct/destruct iterate a snapshot so a child lifecycle hook
  that mutates the group cannot skip siblings.
- A background construct/destruct racing `dispose()` could resurrect the
  VM and publish post-dispose status messages; `Disposed` is now terminal
  in `_setStatus` and the scheduled work (spec/02 invariant 3).
- `RxDispatcher.default()`'s doc no longer inverts the rxjs scheduler
  semantics (queueScheduler is a synchronous trampoline; asapScheduler is
  a Promise microtask).
- `FormVM` no longer advances its snapshot when `dispose()` runs during
  the persister await (rxjs silently swallowed the emissions, masking the
  state mutation), and `onApproved` now emits the value that was actually
  persisted rather than the live model (parity with C#'s captured
  payload). The deny path is likewise a no-op after `dispose()`, and
  `approveAsync()` on a disposed form no longer invokes the persister.
- `ObservableList.insert` throws `RangeError` for out-of-bounds indexes
  (matching `removeAt`/`replace`) — `splice` silently normalized/clamped
  while the `itemAdded` payload carried the raw index (spec/21 §3.2).
  `CompositeVM.insert` and `GroupVM.insert` get the same bounds check
  (catalogued in ADR-0009).
- `ServicedObservableCollection.splice(0, 0)` no longer emits a `Reset` for
  a mutation that never happened (spec/21 §2.4).
- Post-2.4.0 maintenance backfill: `AggregateVM6` walk/dispose drift and the
  missing `DictionaryEntry` export.

### Added

- `FORM-014` conformance coverage: a disposed `FormVM` is inert — approve
  never invokes the persister, deny does not revert (ADR-0038; pins the
  guards shipped earlier in this release).

- `HierarchicalVM.reparentChild` rejects self- and ancestor-reparenting
  with `Error` instead of silently corrupting the tree (HIER-018).
- `NotificationHub.dispose()` — resolves in-flight waiters with `Pending`,
  completes `pending`, refuses new enqueues, idempotent (NOTIF-017).
- Typed-arity `DerivedProperty` factories `fromOne`..`fromFive` plus the
  `fromMany` alias (ADR-0035 §2 DP2 always claimed TS had them; it never
  did — the recorded three-flavor parity decision is now true).
- Idempotent `dispose()` on `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, and `CompositeCommand` (teardown
  symmetry with the C# IDisposable surface; the decorators own no
  subscriptions).

## [2.4.0] — 2026-06-02

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

## [2.3.0] — 2026-05-31

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

## [2.2.0] — 2026-05-30

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
