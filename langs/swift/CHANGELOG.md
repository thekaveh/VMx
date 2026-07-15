# Changelog — VMx (Swift)

All notable changes to the Swift flavor of VMx are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `BasicModalVM` now atomically registers waiters and claims its first dismissal,
  preventing concurrent dismissal/disposal from losing or resuming a waiter
  more than once.

## [3.22.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Changed

- The existing non-throwing, complete disposal cascade is now part of the
  normative cross-flavor contract (LIFE-013, ADR-0108).

## [3.21.0] — 2026-07-14

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
- Disposing an executing `AsyncRelayCommand` now records cancellation before
  cancelling the task, so the command body observes the terminal request.
- Lifecycle status publication, hook completion, property notifications, and
  terminal cleanup are serialized so concurrent or re-entrant disposal cannot
  resurrect a component or tear down an admitted notification.
- `NotificationHub` now publishes concurrent post, resolve, and disposal
  mutations in FIFO order while late subscribers receive only the current
  pending snapshot.
- `FormVM` now serializes model assignment, validation, deny, approval reset,
  and disposal while allowing admitted mutations to finish their observable
  contract.

## [3.20.1] — 2026-07-14

Implements `spec-v3.20.1` with 391/391 library conformance IDs covered.

### Fixed

- `AsyncRelayCommand` now links parent-task cancellation into its execution
  token so structured-concurrency cancellation reaches the command body.
- `AsyncRelayCommand.cancel()` can no longer lose a request made while the body
  task's cancellation handle is being installed.
- `HierarchicalVM.addChild` returns an ignorable `Result`, rejects cycles, and
  atomically transfers attached children (HIER-018, ADR-0105).

## [3.20.0] — 2026-07-12

Implements `spec-v3.20.0` and keeps Swift at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncResourceVM<Value>` models one cancellable async value with immutable
  Idle/Loading/Ready/Error state and load, reload, and cancel commands
  (`ARES-001..011`, ADR-0100).
- A repository-root SwiftPM facade exposes the existing VMx target and bundled
  fixtures from the public git URL. CI structurally compares the root and
  nested manifests, and the release pipeline requires matching semantic and
  operational tags plus a fresh public-consumer lifecycle smoke test.

### Changed

- Latest-start-wins admission rejects stale completion, optional retention
  keeps the accepted value visible, and acquisition-based cleanup releases
  discarded, replaced, stale, and terminal values exactly once.

## [3.19.0] — 2026-07-12

Implements `spec-v3.19.0` and keeps Swift at full library parity: 380/380
conformance IDs covered.

### Added

- `SearchableState<T>` accepts an optional non-failing `sourceChanges`
  publisher that refreshes the current term after source mutations
  (`SRCH-001..007`, ADR-0099).

### Changed

- Source pulses bypass without resetting term debounce, preserve upstream batch
  boundaries and value-equal emissions, isolate source completion, and cancel
  only the helper-owned subscription on disposal.

## [3.18.0] — 2026-07-12

Implements `spec-v3.18.0` and keeps Swift at full library parity: 373/373
conformance IDs covered.

### Added

- `ObservableMembershipSource` and `AggregateChangeStream<Item>` follow
  committed membership in composites, groups, and both serviced collection
  families while reporting `initial`, `membership`, `item`, or `batch`
  provenance (`AGCH-001..010`, ADR-0098).
- `forComponents` selects standard component property changes; the general
  selector can observe nested local state.

### Changed

- Duplicate occurrences of the same object identity share one selected
  subscription; distinct identities each have their own. Explicit nested
  batches coalesce aggregate output, and idempotent disposal detaches only
  aggregate-owned subscriptions without owning source items.

## [3.17.0] — 2026-07-12

Implements `spec-v3.17.0` and keeps Swift at full library parity: 363/363
conformance IDs covered.

### Added

- `KeyedServicedObservableCollection<Key, T>` adds captured-key `get(_:)`,
  `containsKey`, `upsert`, and `delete(_:)` while retaining ordered serviced
  collection operations (`COL-056..064`, ADR-0097).
- Catchable duplicate-key validation and final-result preflight make
  `replaceAll` and indexed rekeying atomic.

### Changed

- Key lookup and present-key upsert use the captured-key index; item lifecycle
  remains caller-owned and external transactions still defer only hub delivery.

## [3.16.0] — 2026-07-12

Implements `spec-v3.16.0` and keeps Swift at full library parity: 354/354
conformance IDs covered.

### Added

- `ServicedObservableCollection<Element>` adds indexed removal, named
  replacement, snapshot-based `replaceAll`, and catchable `move(from:to:)`
  while retaining `setAt`, `removeLast`, and Equatable value removal
  (`COL-048..055`, ADR-0096).
- Collection-change messages retain `index` and add precise `oldIndex` /
  `newIndex` positions, including one Move delivered locally before the
  optional hub sees the final state.

### Changed

- Empty clear, empty-to-empty replacement, and same-index move no-ops are
  notification-free; serviced mutations never acquire item lifecycle ownership.

## [3.15.0] — 2026-07-11

Implements `spec-v3.15.0` and keeps Swift at full library parity: 346/346
conformance IDs covered.

### Added

- `subscribeValue(...)` observes selected state from one fixed VM through its
  hub, provides `Equatable` default and custom comparator overloads with optional
  immediate delivery, reports current/previous values, and returns an
  `AnyCancellable` teardown handle. Re-entrant ordering, batching, cancellation,
  and subscriber failure behavior follow the existing hub contract
  (`SUBV-001..004`, ADR-0095).

## [3.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps Swift at full library parity: 342/342
conformance IDs covered.

### Changed

- The declared current/minimum spec line advances to 3.14.0. The Swift runtime
  surface is unchanged because ADR-0094 records TypeScript-only message
  predicate ergonomics and adds no language-neutral conformance requirement.

## [3.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps Swift at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republishModel()`, which retains model and hint state, skips assignment,
  hinter, and callback work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [3.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps Swift at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVM.setModel` now uses its configured equality to suppress a no-op
  candidate, then publishes exactly one model `PropertyChangedMessage` after
  model, validation, and approve-command state settle (`FORM-030`, ADR-0092).
- Compatibility: unequal edits are now visible on the configured hub, while a
  distinct equality-equal candidate is retained silently instead of replacing
  the live model and rerunning validators.

## [3.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps Swift at full library parity: 340/340
conformance IDs covered.

### Changed

- Modeled component and `FormVM.setModel` assignment return before equality,
  retained-state, hinting, validation, command-state, callback, or notification
  work after disposal (`DISP-014`, ADR-0091). The read-only modeled component's
  internal update path inherits the same terminal guard.

## [3.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps Swift at full library parity: 339/339
conformance IDs covered.

### Added

- `ComponentVMBase.own(...)` registers cleanup closures or Combine cancellables
  for exactly-once LIFO terminal cleanup; the existing public read-only `hub`
  now forms the common cross-flavor baseline (`DISP-007..013`).

## [3.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps Swift at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList.replaceAll(...)` snapshots sequence input and emits one Reset
  plus cardinality-dependent `Count` (`COL-040..047`).
- `withBatch` now accepts throwing closures and restores batch state with
  `rethrows` semantics.

## [3.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps Swift at full library parity: 324/324
conformance IDs covered.

### Added

- `attachMany(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [3.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps Swift at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `resetOnApproved(...)` for declarative throwing
  post-persist reset, including independent snapshots, revalidation,
  deterministic race semantics, and existing approval error routing
  (`FORM-024..029`).

## [3.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps Swift at full library parity: 310/310
conformance IDs covered.

### Added

- `raiseCanExecuteChanged()` on `RelayCommand`, `RelayCommandOf`, and
  `AsyncRelayCommand`, including exact live, repeated, trigger-additive,
  in-flight, and post-dispose behavior (`CMD-014..019`).

## [3.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps Swift at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `VMCollection` and selection-specific `SelectableVMCollection`
  protocols, including the complete group/composite mutation surface.
- Catchable, atomic identity-preserving `move(from:to:)` and `.move`
  collection events (`COL-032..039`).

## [3.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps Swift at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

## [3.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps Swift at full library parity: 290/290
conformance IDs covered.

### Added

- Subclass-facing `_notifyPropertyChanged` for emitting one hub
  `PropertyChangedMessage` followed by one local property-change notification
  (`CVM-007..009`).

### Changed

- Component, modeled-component, composite, aggregate, and flagship Notes
  Showcase setters now use the shared helper after equality checks and
  assignment.

## [3.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps Swift at full library parity: 287/287
conformance IDs covered.

### Added

- `TransactionalMessageHubProtocol` and `try hub.batch { ... }` for nested,
  lossless FIFO transactions (`HUB-008..013`).
- Iterative re-entrant delivery, serialized concurrent producers, and an
  injectable debug-only publish-cycle diagnostic naming message types.

### Changed

- `NullMessageHub` executes transaction bodies while continuing to publish
  nothing.

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps Swift at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf<T>` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.
- Options-value `create(_:)` factories for the common `ComponentVM`,
  `ComponentVMOf`, `CompositeVM`, and `GroupVM` types (`BLD-006`).
- Collection + message-hub surface parity: value-based `remove(_:)` on
  `ObservableList` / `ServicedObservableCollection`, strict-insert
  `add(_:_:_:)` on `ObservableDictionary`, and the `whenPropertyChanged` /
  `propertyValueChangedMessagesFor` hub helpers (spec/03 §7, spec/21).

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.

### Fixed

- `reconstruct()` now rolls back to the prior settled lifecycle state when its
  destruct or construct hook throws.
- Concurrent `dispose()` calls invoke `_onDispose()` at most once.
- `AsyncRelayCommand` is now inert after disposal, synchronizes its in-flight
  state, and fire-and-forget cancellation no longer emits on `errors` when
  `throwOnCancel()` is set.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes, and serializes token/items state
  against concurrent disposal.
- Group children no longer report enabled child selection into a group, and
  composite/group lifecycle cascades snapshot children before invoking hooks.
- Background-form lifecycle now marshals the terminal `Constructed` /
  `Destructed` transition onto `IDispatcher.Foreground` (`VMX-025`, spec/11 §4),
  matching C#/Python: SwiftUI subscribers observe lifecycle completion on the
  main thread instead of the background pool thread. `THR-002` now asserts the
  three-phase behavior (background flush leaves the VM `Constructing`; the
  terminal transition lands only after the foreground flush).

## [3.0.0] — 2026-06-28

The **v3 framework overhaul**. Implements `spec-v3.0.0`; the Swift-specific
convergence is ADR-0053. (This in-development version was grown to full library
parity + the notes-showcase flagship across ADRs 0059–0067; it is unpublished
and untagged, so those additive changes land here rather than in a bumped
version — see ADR-0066.)

### Added

- **Cross-module subclassing support for `ComponentVMBase`** (ADR-0066). The
  subclass-facing messaging surface — `hub`, `dispatcher`, and
  `_raisePropertyChanged(_:)` — is now `public` (read-only for the two
  properties) instead of `internal`, so consumers in another module can
  subclass `ComponentVMBase` and publish hub messages / fire the
  `propertyChanged` side-channel. Swift has no `protected`; `internal` did not
  cross the module boundary, so the base was previously only subclassable
  in-module. Purely additive — no behavior or conformance change (still
  237/237). Surfaced while building the Swift notes-showcase flagship.

### Changed

- **BREAKING:** Illegal lifecycle transitions and a non-child `current`
  assignment now **throw catchable errors** (`StatusTransitionError` /
  `CompositeMembershipError`) instead of trapping via `preconditionFailure`
  (ADR-0053, superseding ADR-0037 §2.5). `construct()` / `destruct()` /
  `reconstruct()` and `setCurrent(_:)` are throwing; `LIFE-005` / `LIFE-006` /
  `LIFE-008` now assert a catchable throw. `dispose()` stays terminal/idempotent
  and never throws; the read-only model setter (`CVM-003`) still traps because
  Swift setters cannot throw. The conformance subset grows 41 → 42 (+`LIFE-008`).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.0 subset remains MIT-licensed.

## [2.6.0] — 2026-06-13

Implements the spec-v2.6.0 subset. Adds two declarative selection hooks
to the non-modeled composite builder (the modeled composite is outside
Swift's documented subset; see `README.md` §5).

### Added

- `CompositeVMBuilder<Child>.current(_:)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder<Child>.onCurrentChanged(_:)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty<T>` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `onCurrentChanged` (behavior change).
- Conformance subset bumped 39 → 41 (+ COMP-025, COMP-026).

## [2.5.0] — 2026-06-10

Implements the spec-v2.5.0 subset (ADR-0037). 39 conformance IDs claimed
(honest recount — see the corrected 2.4.0 notes below).

### Changed

- **`ParentVM.supportsSelection` removed.** spec/05 §5 defines
  `can_select()` without a parent-slot condition, so a constructed group
  child now reports `canSelect() == true` and `select()` is a no-op,
  matching C# / Python / TypeScript. Code conforming to `ParentVM` no
  longer declares the member.
- **Hub `PropertyChangedMessage` names are camelCase everywhere** per the
  Swift idiom (spec/04 §4, ADR-0037): `"model"`, `"modeledHint"`,
  `"current"`, `"isCurrent"`, `"component1".."component6"`.
- Illegal lifecycle transitions remain traps (`preconditionFailure`) — now
  a *documented* divergence (spec/02 §2, ADR-0037) rather than an accident;
  LIFE-005/006 are claimed at the gating-predicate level and LIFE-008 is
  not claimed.

### Fixed

- **The five built-in commands were permanent no-op placeholders** —
  `selectCommand.canExecute()` returned `true` for orphan VMs and
  `execute()` silently discarded. They are now wired to the spec/05 §5
  predicates/tasks with the status trigger driving `canExecuteChanged`.
- `ReadonlyComponentVMOf.builder()` resolved to the inherited writable
  builder and produced a writable VM; the dedicated
  `ReadonlyComponentVMOfBuilder<Model>()` is now the readonly entry point.
  (A static `builder()` shadow on the subclass is not expressible in
  Swift — a different-return variant is ambiguous at annotation-free call
  sites and a same-signature redeclaration is an illegal static override —
  so the inherited `builder()` still resolves and builds a value
  statically typed `ComponentVMOf`; prefer the dedicated builder.)
- `ComponentVMOf.builder()` actually defaults `modelEquals` to `==` for
  `Equatable` models, as the documentation always claimed (the builder
  previously fell back to an always-false predicate).
- A background construct/destruct racing `dispose()` could resurrect the VM
  and publish post-dispose status messages; `.disposed` is now terminal in
  `_setStatus` and the scheduled work (spec/02 invariant 3). The same
  invariant now also gates the `_setIsCurrent` / `_setModel` hub sends,
  which previously published from disposed VMs.
- Conformance-ID citations in the test suite re-mapped against
  `spec/12-conformance.md` (~30 of 53 were shifted or vacuous).

### Added

- `VMxVersion.current` / `VMxVersion.minSpecVersion` constants (parity with
  the other flavors' programmatic version exports).
- New tests for CVM-001/003/006, AGG-004, CMD-006, BLD-003/004, GRP-002,
  and the Equatable builder default.

## [2.4.0] — 2026-06-02

**First release of the Swift flavor.** Implements a subset of spec
v2.4.0 covering the core viewmodel family + builders. This is a
skeleton release; the follow-up PR will widen coverage to full
cross-language parity.

### Added

- **`ConstructionStatus`** — five-state lifecycle enum (`.destructed`,
  `.constructing`, `.constructed`, `.destructing`, `.disposed`) with
  stable string `name` for fixture round-trip.
- **`ComponentVMBase`** — open base class for every VMx viewmodel.
  Manages the lifecycle state machine, hub publishing, the built-in
  command set, and parent/child selection delegation.
- **`ComponentVM`** — non-modeled leaf viewmodel.
- **`ComponentVMOf<Model>`** — modeled leaf viewmodel with a settable
  model, optional `modeledHinter`, and optional `modelEquals` predicate
  (defaults to `==` for `Equatable` models via a convenience
  initialiser).
- **`ReadonlyComponentVMOf<Model>`** — read-only modeled variant.
- **`CompositeVM<Child>`** — homogeneous-child container with a
  `current` selection slot.
- **`GroupVM<Child>`** — homogeneous peer-child container without a
  current slot.
- **`AggregateVM1..AggregateVM6`** — fixed-arity heterogeneous
  component-slot containers.
- **`RelayCommand`** — concrete `Command` with predicate + task closures
  and additive trigger publishers, backed by Combine.
- **Services:** `MessageHubProtocol` + `MessageHub` (Combine-backed),
  `NullMessageHub.INSTANCE`, `Dispatcher` protocol, `DefaultDispatcher`,
  `ImmediateDispatcher.INSTANCE`, `NullDispatcher.INSTANCE`.
- **Messages:** `Message` protocol, `PropertyChangedMessage`,
  `ConstructionStatusChangedMessage`.
- **Builders:** immutable fluent builders for `ComponentVM`,
  `ComponentVMOf`, `CompositeVM`, `GroupVM`, `AggregateVM1..6`,
  `RelayCommand`. Each ships a `withNullServices()` wither per
  ADR-0035. `BuilderValidationError` is thrown by `build()` when a
  required field is missing.

### Conformance subset

*(Corrected post-release — see ADR-0037. The list below originally
claimed `LIFE-001..013`, `CVM-001..006`, `COMP-001..010`, `GRP-001..006`,
`AGG-001..006`, `CMD-001..007`, `BLD-001..005`; several of those IDs'
behaviors did not exist in this release.)*

- `LIFE-001..007, 009, 010, 012, 013` — lifecycle state machine
  (LIFE-005/006 assert the gates; the raise is a trap).
- `CVM-002, 004, 005` — modeled component basics, as released.
- `COMP-003..005`, `GRP-003, 004` — lifecycle cascades + child-select.
- `AGG-001..006` — AggregateVM1..6 parametric coverage.
- `CMD-001..004` — RelayCommand task + predicate + triggers.
- `BLD-001, 002, 004, 005` — builders immutable + validation + defaults.

### Deferred to follow-up PRs

`HUB-*`, `PROP-*`, `THR-*`, `FWD-*`, `CAP-*`, `NULL-*`, `DPROP-*`,
`CMDD-*`, `NOTIF-*`, `EXP-*`, `LOC-*`, `COL-*`, `HIER-*`, `DIA-*`,
`FORM-*`, `UTIL-*`, and the fixture-backed `LIFE-011`. See README
§5 for the full status table.
