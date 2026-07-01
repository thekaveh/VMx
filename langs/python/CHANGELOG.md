# Changelog

All notable changes to the Python flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps Python at full library parity: 279/279
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.

### Fixed

- `AsyncRelayCommand` is now inert after disposal and no longer emits
  `can_execute_changed` into a disposed Rx subject when an in-flight task
  completes after disposal.
- `TokenPagedComposition` skips in-flight load/refresh mutation and notifications
  if it is disposed before the fetch completes.

## [3.0.0] — 2026-06-28

The **v3 framework overhaul** — a breaking release that hardens the
lifecycle/dispose concurrency path and reconciles the public surface across
flavors. Implements `spec-v3.0.0`. See ADRs 0047–0058 and
`docs/audit/2026-06-27-vmx-merged-critique.md`.

### Added

- Positional-options construction for the common VMs — a `create(...)` classmethod
  taking keyword-only arguments alongside the unchanged fluent builders:
  `ComponentVM.create(...)`, `ComponentVMOf.create(...)`, `CompositeVM.create(...)`,
  `GroupVM.create(...)`. Delegates to the builder, so required-field validation
  (`BuilderValidationError`) and the resulting VM are identical to the fluent path
  (ADR-0055; VMX-020).
- `AsyncRelayCommand` — an additive async command that flows asyncio task
  cancellation into a long-running coroutine and adds a `cancel()` method, closing
  the cancellation gap the synchronous `RelayCommand` had. Cancellation is
  non-throwing to the caller by default with an opt-in throwing mode;
  fire-and-forget task faults route to an `errors` observable. `RelayCommand` is
  unchanged (ADR-0056; CMD-012; VMX-052).
- `FormVM` surfaces approve-path persister failures on a new `approve_errors`
  observable instead of swallowing them; `is_dirty` uses the model's own value
  equality and the default snapshot is a deep value-copy (`copy.deepcopy`), both
  injectable; `on_approved` is pinned to the persisted value (ADR-0048; FORM-015).

### Removed

- **BREAKING:** Removed the legacy v1.0.0 `RelayCommandOfT` /
  `RelayCommandOfTBuilder` identity aliases (ADR-0052; VMX-095, deferral recorded
  in ADR-0009). Use the canonical `RelayCommandOf` / `RelayCommandOfBuilder`.
- **BREAKING:** Removed the legacy `AggregateVMBuilder1..6` identity aliases
  (ADR-0052; VMX-081). The concrete builders are the canonical
  `AggregateVM1Builder..6Builder`.
- **BREAKING:** Removed `null_message_hub_of` from the top-level `vmx` export
  (ADR-0052; VMX-081). It remains available as `from vmx.services import
  null_message_hub_of` for the narrow-typing case; the package root now offers a
  single null hub, `NULL_MESSAGE_HUB`.

### Changed

- **BREAKING:** `HierarchicalVM.__init__` now requires explicit `hub` and
  `dispatcher` arguments (the silent `MessageHub()` / `RxDispatcher.immediate()`
  defaults are removed) so a tree node can no longer acquire an isolated hub
  (ADR-0052; VMX-080). The builder is unchanged — it already required
  `services(hub, dispatcher)` and still offers `with_default_services()`.
- **BREAKING:** `ConfirmationDecoratorCommand.execute()` (synchronous
  fire-and-forget) now surfaces a rejecting `confirm` delegate or a throwing inner
  command on a new `errors` observable instead of swallowing them; the awaitable
  `execute_async()` keeps its raise behavior (ADR-0049; CMDD-010).
  `ModeledCrudCommands` update/delete `can_execute` is now reactive to
  current-selection change so bound buttons refresh (ADR-0049; VMX-011).
- Relicensed from MIT to **Apache-2.0** (ADR-0043). Effective from this point
  forward; the already-published 2.6.1 artifact remains MIT-licensed.

### Fixed

- **Lifecycle/dispose concurrency cluster (ADR-0047):** status transitions are
  atomic and dispose-safe behind a per-VM guard; background lifecycle completions
  marshal their terminal emission onto the foreground dispatcher; a post-dispose
  `is_current` change is a silent no-op; and a throwing `on_construct`/`on_destruct`
  hook rolls `status` back to the prior settled state (LIFE-008, the new LIFE-014).

## [2.6.1](https://github.com/thekaveh/VMx/compare/python-v2.6.0...python-v2.6.1) (2026-06-17)


### Documentation

* **python:** RELEASING URL-validation checklist + bootstrap tag-ordering gotcha + PyPI badge ([#24](https://github.com/thekaveh/VMx/issues/24)) ([cef3629](https://github.com/thekaveh/VMx/commit/cef3629d623e694350989754c225de1a9c27f909))

## [2.6.0] — 2026-06-13

Implements `spec-v2.6.0`. Adds two declarative selection hooks to the
composite builders, plus four ADRs capturing absorption-audit decisions.

### Added

- `CompositeVMBuilder[VM].current(selector)` — declarative initial-current
  selector (ADR-0042, COMP-025).
- `CompositeVMBuilder[VM].on_current_changed(callback)` — synchronous
  post-change selection callback (ADR-0042, COMP-026).
- Same hooks on the modeled `CompositeVMOfBuilder[M, VM]`.

### Documentation

- ADR-0039 — `INotifyPropertyChanging` not supported (teaching).
- ADR-0040 — `IProperty[T]` reactive backing-field not adopted (teaching).
- ADR-0041 — Single disposable lifecycle, no two-tier bags (teaching).
- ADR-0042 — `CompositeVMBuilder.current` + `on_current_changed` (behavior change).

## [2.5.0] — 2026-06-10

Implements `spec-v2.5.0` (ADR-0037).

### Fixed

- `FormVM.dispose()` is idempotent — a second call raised reactivex
  `DisposedException` (rxjs no-ops, C# guards).
- `CompositeVM.clear()` routes through the current-selection setter; the old
  current child no longer keeps `is_current == True` with no notification.
- `PagedComposition` subscribes `on_item_replaced`; `replace()` on the
  current page refreshes `items`.
- `ObservableList.clear()` emits `PropertyChanged("Count")` after `Reset`
  when the count changed (spec/21 §3.3).
- `GroupVM` construct/destruct iterate a snapshot so a child lifecycle hook
  that mutates the group cannot skip siblings.
- A background construct/destruct racing `dispose()` could resurrect the
  VM and publish post-dispose status messages; `DISPOSED` is now terminal
  in `_set_status` and the scheduled work (spec/02 invariant 3).
- `FormVM.approve_async` no longer raises `DisposedException` when
  `dispose()` runs during the persister await (mirrors the C# guard).
- `NotificationHub.dispose()` tolerates waiters whose event loop is
  already closed instead of raising and skipping the remaining waiters.
- `ObservableList.remove_at`/`replace` normalize negative indexes before
  emitting, so the event payload carries the spec-mandated
  index-before-removal instead of a raw `-1` (spec/21 §3.2; TS/C# raise
  on negative indexes by design). Out-of-range negatives raise
  `IndexError` instead of wrapping to a valid index.
- `FormVM`'s deny path is a no-op after `dispose()` (previously it
  reverted the model and re-published hub messages on a disposed form;
  same guard added in C# and TS). `approve_async()` on a disposed form
  is likewise a full no-op — the persister is no longer invoked.
- `ObservableList.insert` emits the actual insertion index: in-range
  negatives normalize and out-of-range indexes clamp per stdlib
  `list.insert` semantics, instead of the raw argument leaking into the
  `ItemAdded` payload (spec/21 §3.2). The same normalization applies to
  `ServicedObservableCollection.insert`, `CompositeVM.insert`, and
  `GroupVM.insert` (catalogued vs the C#/TS fail-fast contracts in
  ADR-0009).
- `FormVM`'s `on_approved` now emits the value that was actually
  persisted rather than the live model (parity with C#'s captured
  payload under a racing `set_model`).
- `NotificationHub` emits pending snapshots inside the lock (ordering +
  dispose-race discipline, mirroring C#).
- Post-2.4.0 maintenance backfill: `AggregateVM1..6` dispose ordering
  (LIFE-013) and aggregates walk/dispose drift.
- `FormVM.builder()` raised `TypeError` on every call (subscripted
  instantiation of a frozen+slots dataclass); it was the only builder
  entrypoint no test had ever exercised.
- `SearchableState.can_search()` returned `False` when the first item was
  a legal `None` value (sentinel conflation; C#/TS were unaffected).
- `ConfirmationDecoratorCommand`'s fire-and-forget done-callback raised
  `CancelledError` into the event loop when the task was cancelled.
- `fluent.confirm()` now types its callback as
  `Callable[[], Awaitable[bool]]`, matching the constructor contract it
  forwards to (a sync callback previously passed mypy and failed at
  `await`).

### Added

- `FORM-014` conformance coverage: a disposed `FormVM` is inert — approve
  never invokes the persister, deny does not revert (ADR-0038; pins the
  guards shipped earlier in this release).

- `HierarchicalVM.reparent_child` rejects self- and ancestor-reparenting
  with `ValueError` instead of silently corrupting the tree (HIER-018).
- `NotificationHub.dispose()` — resolves in-flight waiters with `PENDING`,
  completes `pending`, refuses new enqueues, idempotent (NOTIF-017).
- The `Dispatcher` protocol is exported from the top-level `vmx` package
  (parity with TS `IDispatcher` / C# `IDispatcher`).
- Idempotent `dispose()` on `DecoratorCommand` and
  `ConfirmationDecoratorCommand` (teardown symmetry with the C#
  IDisposable surface; the decorators own no subscriptions).

## [2.4.0] — 2026-06-02

Implements spec v2.4.0 — umbrella publication-readiness + Swift flavor
sibling + example-app theming scenario contract + test-coverage backfill
(ADR-0036). Purely additive at the surface level; no behaviour changes
to existing Python APIs.

### Added

- **ThemeVM scenario contract** (example apps): the v2.4.0
  `spec-v2.4.0` cycle defines a normative shape for example-app
  theming (`ThemeModel` + `ThemeVM : ComponentVMOf[ThemeModel]` +
  per-framework `ThemeAdapter`) built from the existing core
  primitives (`ComponentVMOf[M]`, `DerivedProperty[T]`, `RelayCommand`,
  `MessageHub`). No new core types are introduced; the contract is
  implemented by the Textual Notes-Showcase flagship under
  `examples/python/textual/notes_showcase/`. See
  `spec/proposals/2026-06-02-theme-vm-scenario.md` + ADR-0036 §2.C.

### Fixed

- **Aggregate parametric test coverage backfill.** The
  `AggregateVM1..6` test suite was expanded with parametric
  per-arity cases for construction, destruction, modeled-hint
  propagation, and dispose-cascade ordering — bringing aggregate-family
  line coverage to **100%** across all six arities. Existing
  Notes-Showcase edge cases (filter / search / paging interaction,
  capability-aware action-bar gating) gained dedicated tests in the
  same pass. No production code changed; tests only.

### Conformance

- 5 new IDs (`THEME-001..005`); running total goes from 227 to **232**.
  The Python flavor implements `THEME-001..005` as part of the Textual
  Notes-Showcase flagship's conformance suite (the contract is
  scenario-level, not a core library addition).

### Min spec version

- 2.4.0 (previously 2.3.0).

## [2.3.0] — 2026-05-31

Implements spec v2.3.0 — builder pattern audit follow-through (ADR-0035).
Purely additive at the surface level. One behaviour change brings
`CompositeVMBuilder` and `GroupVMBuilder` into compliance with the
existing spec §3 contract (see Fixed below); callers that were relying
on the previously-lazy validation were already buggy.

### Added

- **`FormVMBuilder`** (`vmx.forms`) — fluent immutable builder for
  `FormVM` with `.initial(...)` and `.persister(...)` required, and
  optional `.hub(...)`, `.strict(bool)`, `.snapshotter(...)`. Validates
  at `build()`. Conformance: `FORM-011..013`. See ADR-0035 §FV1/FV2.
- **`HierarchicalVMBuilder`** (`vmx.hierarchical`) — fluent immutable
  builder for `HierarchicalVM` with `.model(...)`,
  `.children_factory(...)`, `.services(hub, dispatcher)` required, and
  optional `.name(...)`, `.hint(...)`, `.eager_children(bool)`. Adds
  `.with_default_services()` Wither for opt-in implicit defaults.
  Validates at `build()`. Conformance: `HIER-015..017`. See ADR-0035
  §H1/H2/H3.
- **`with_null_services()`** Wither extension on `ComponentVMBuilder`
  (and friends) — chainable convenience that wires
  `NULL_MESSAGE_HUB` + `NULL_DISPATCHER` in one call, for parity with
  the C# `WithNullServices()` extension. See ADR-0035 §SV1.
- **Typed-arity DerivedProperty factories** — `DerivedProperty.from_one`
  through `DerivedProperty.from_five` with per-source type inference;
  `DerivedProperty.from_many` retained as alias of the existing
  `from_sources(...)` for arbitrary-N consumers. See ADR-0035 §DP2.

### Fixed

- `CompositeVMBuilder.build()` and `GroupVMBuilder.build()` now raise
  `BuilderValidationError` when `children` is unset, matching the
  spec/10 §3 contract and the TypeScript flavor's existing behaviour.
  Previously the Python flavor silently accepted a missing `children`
  factory and raised later at `on_construct`. See ADR-0035 §CP1/GR2.

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

- **`HierarchicalVM`** (`vmx.hierarchical`) — first-class recursive tree VM with
  lazy/eager child loading, depth-first construction, materialized path,
  parent-change and structural-change hub messages. `TreeStructureChangedMessage`
  new type. (ADR-0028; HIER-001..014)
- **`DialogService`** + **`NullDialogService`** (`vmx.dialogs`) — host-side
  contract for modal interactions (file pick, confirm prompt, severity-tagged
  notify) distinct from `INotificationHub`. (ADR-0029; DIA-001..008)
- **`FormVM`** (`vmx.forms`) — snapshot/revert edit lifecycle (ORM-agnostic).
  `deny_command`, `approve_command`, `on_approved` event, optional strict mode.
  `FormRevertedMessage` new type. (ADR-0030; FORM-001..010)
- **`NotificationVM`** + **`ConfirmationVM`** (`vmx.notifications`) — render-side
  VMs with auto-dismiss (60s/300s default), opacity decay, dismiss/approve/reject
  commands. (ADR-0031; NOTIF-011..016)
- **`ServicedObservableCollection`** (`vmx.collections`) — observable collection
  with hub publication. (ADR-0024; COL-001..004)
- **`ObservableList`** (`vmx.collections`) — granular per-mutation events
  (item_added/removed/replaced/reset) with batch suppression. (ADR-0026;
  COL-005..009, COL-023)
- **`ObservableDictionary`** (`vmx.collections`) — composite-key observable
  dictionary with observable keys1/keys2 views and hub publication. (ADR-0025;
  COL-010..015, COL-022)
- **`PagedComposition`** (`vmx.collections`) — paging decorator over any
  composition implementing `Pageable`. (ADR-0023; COL-016..021)
- **`Filterable`** + **`Pageable`** (`vmx.capabilities`) — two new capability
  protocols. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command helpers** (`vmx.commands`) — `confirm(…)`, `precede_with`,
  `succeed_with`, `wrap_with` extension helpers over commands. (ADR-0027;
  CMD-008..011)
- **`property_value_changed_messages_for`** helper (`vmx.messages`) —
  function that filters `PropertyChangedMessage` events for a given
  sender + property name and returns an observable stream of the
  property's value snapshots. (ADR-0032; informative)
- **Conformance**: 67 new IDs (total 219).

### Fixed

- `CompositeVM.__setitem__` now clears `current` to None when the
  replaced slot held the current selection, mirroring `_remove_at`.
  Previously `_current` would silently dangle on the removed child.
- `AggregateVM1.._on_construct` now disposes the previous slot
  instance before invoking the factory on Reconstruct, so the old
  VM's hub subscriptions and command Subjects are released instead of
  lingering until the hub itself is disposed. (Parity with the C# fix.)
- `NotificationHub.resolve()` now schedules `future.set_result` via
  `loop.call_soon_threadsafe`, making `resolve()` safe to call from a
  thread other than the future's owning event loop (`asyncio.Future`
  itself is not thread-safe).
- `CompositeCommand.dispose()` no longer iterates a permanently-empty
  `_subscriptions` list (dead state). The merged `can_execute_changed`
  observable is lazy; subscribers' own disposables tear down the
  merged chain when they unsubscribe.
- `SearchableState.search_term` setter no longer pushes the new value
  through the debounce/recompute pipeline when it equals the current
  value (spec wording: "emission on a new value").
- `SearchableState.can_search` now uses `next(iter(...), None) is not None`
  instead of `any(True for _ in ...)`, materialising one element
  instead of the entire iterable.
- `DecoratorCommand.execute` now wraps the inner `execute` call in
  try/finally so the `post_execute` callback always runs — a "busy"
  flag set in `pre_execute` no longer gets stuck when the inner
  command raises.

### Changed

- `DerivedProperty`, `SearchableState`, and `ExpandableState` `dispose()`
  methods now call `.dispose()` after `.on_completed()` on each Subject,
  matching the project-wide pattern in `MessageHub` and `RelayCommand`.
- `properties.derived._apply` uses `cast()` instead of
  `assert isinstance(values, tuple)` so the runtime guard is not
  stripped by `python -O`.

## [2.0.0] — 2026-05-25

Implements spec v2.0.0 — capability micro-interfaces, derived properties,
search/filter, expand/collapse, modeled-CRUD commands, null-object services,
opt-in notifications sub-package, and a localization hook.

### Added
- **Capabilities** (`vmx.capabilities`): 20 opt-in micro-interfaces —
  `ISelectable`, `IDeselectable`, `ISelectionTogglable`, `IExpandable`,
  `ICollapsible`, `IExpansionTogglable`, `ISearchable`, `IClosable`,
  `IApprovable`, `ICancelable`, `INewCreatable`, `IDeletable`,
  `IUpdatable`, `ISavable`, `ICurrentDeletable`, `ICurrentUpdatable`,
  `IManagable`, `IConstructable`, `IDestructable`, `IReconstructable`
  (see `src/vmx/capabilities/`).
- **Helpers** (`vmx.capabilities`): `SearchableState[TItem]` (debounced
  filter), `ExpandableState` (expand/collapse + observable change).
- **Derived properties** (`vmx.properties`): `DerivedProperty[TValue]` +
  `from_sources(*sources, transform)` factory for N-source computed values
  with `distinct_until_changed` + optional write-back.
- **Commands**: `ConfirmationDecoratorCommand` + the abstract
  `DecoratorCommand` base, `make_confirm` helper,
  `ModeledCrudCommands[M, VM]` for the CRUD trio
  (create / update_current / delete_current) on modeled composites.
- **Null-object services** (per ADR-0017): `NullMessageHub`, `NullDispatcher`,
  `NullLocalizer`, plus `NullNotificationHub` (in the notifications package).
- **Localization** (`vmx.localization`): `ILocalizer` Protocol and
  `NullLocalizer` (identity translator) — the only opinionated localizer
  shipped in core.
- **Notifications sub-package** (`vmx.notifications`, opt-in): `Notification`,
  `NotificationType`, `NotificationReaction`, `INotificationHub` +
  `NotificationHub` reference impl + `NullNotificationHub`.
- **Tree utilities**: `walk_expanded(root)` — variant of `walk` that only
  descends into expanded composites (uses the new `IExpandable` capability).
- **Conformance**: 77 new IDs (`CAP-NNN`, `DPROP-NNN`, `NOTIF-NNN`,
  `LOC-NNN`, `COMP-014..024`, `GRP-007..010`) — total now 152 IDs.

### Internal
- `vmx.builders._validation.require_field` / `require_services` return
  narrowed values for tighter mypy --strict downstream typing.
- Dispose paths across `Modeled*` / `Searchable*` / `Expandable*` /
  `Derived*` are guarded with `_disposed` for idempotence.

### Notes
- The legacy aliases `RelayCommandOfT` / `RelayCommandOfTBuilder` and
  `AggregateVMBuilder1..5` continue to ship in v2.0.0; their removal has
  been deferred to **vmx v3.0.0** (next major). See ADR-0009.

## [1.2.0] — 2026-05-23

### Added
- `RelayCommandOf` and `RelayCommandOfBuilder` are now the canonical names for
  the parameterised command + builder pair, matching the TypeScript flavor's
  `RelayCommandOf` / `RelayCommandOfBuilder`.
- `AggregateVM1Builder` through `AggregateVM5Builder` are now the canonical
  builder names for the aggregate VMs, matching the TypeScript flavor's
  `AggregateVMNBuilder` shape.

### Deprecated
- `RelayCommandOfT` and `RelayCommandOfTBuilder` remain as identity aliases for
  backward compatibility. Removal deferred to **vmx v3.0.0** (was originally
  targeted for v2.0.0; see v2.0.0 Notes and ADR-0009).
- `AggregateVMBuilder1` through `AggregateVMBuilder5` remain as identity aliases
  for backward compatibility. Removal deferred to **vmx v3.0.0** (was originally
  targeted for v2.0.0; see v2.0.0 Notes and ADR-0009).

### Internal
- Per-suppression rationale comments added at every `# type: ignore` in
  `vmx.forwarding.composite` and `vmx.components.builders` (10 + 2 sites).
- `vmx.builders._validation` now declares parameters as `object | None` instead
  of `Any`, with a module docstring explaining why a Hub/Dispatcher Protocol is
  intentionally not used.
- `vmx.components.base` empty B027-silenced override hooks now carry an inline
  reason in their `noqa` comment.

## [1.1.0] — 2026-05-23

### Added
- Implements spec-v1.1.0 on top of the v1.0.0 surface.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `.auto_construct_on_add(bool)` builder option. When `True`, a child added after the container reaches `Constructed` is automatically constructed before the `CollectionChanged(Add)` event fires.
- `CompositeVM` / `CompositeVMOf` / `GroupVM`: new `batch_update()` method returns a context manager / disposable that suppresses per-mutation `CollectionChanged` events. The outermost handle disposal emits a single `CollectionChanged(Reset)` event iff any mutations occurred during the batch.
- New `vmx.tree` module with `walk(root)` (DFS pre-order generator) and `find(root, predicate)` (short-circuiting first-match).
- New conformance IDs: COMP-012, COMP-013, GRP-005, GRP-006, UTIL-001, UTIL-002, UTIL-003 (75/75 catalog coverage).
- Top-level `vmx.collections` module hosting the canonical `CollectionChangedEvent` (unified across composites and groups).
- Top-level `vmx` re-exports for the most-used types (`from vmx import ComponentVMOf, MessageHub, RxDispatcher, walk, find`).

### Fixed
- `GroupVM.dispose()` now cascades depth-first, matching the spec's LIFE-013 contract and the C# behavior.
- `CompositeVM` factory children now emit `CollectionChanged(Add)` events (previously silent), matching C#.
- Removed a stale "scaffolding state / Phase 3" docstring from `vmx/__init__.py`.

## [1.0.0] — 2026-05-23

### Added
- Full implementation of spec-v1.0.0:
  - Lifecycle: `ConstructionStatus` IntEnum + `StatusTransitionError` + JSON-fixture-backed transition validator
  - Messages: `Message`/`TypedMessage` Protocols + `PropertyChangedMessage` + `ConstructionStatusChangedMessage` frozen dataclasses
  - Services: `MessageHub` (Subject-backed hot stream with per-subscription exception isolation) + `Dispatcher` Protocol + `RxDispatcher` (with `immediate()` and `asyncio(loop)` factories)
  - Commands: `RelayCommand` + `RelayCommandOfT[T]` with reactive triggers and immutable frozen-dataclass builders; Execute is gated on can_execute
  - Components: `ComponentVM`, `ComponentVMOf[M]`, `ReadonlyComponentVMOf[M]` with full lifecycle, modeled hint, 5 built-in commands, async variants
  - Composites: `CompositeVM[VM]` + `CompositeVMOf[M, VM]` with selection contract, MutableSequence + Observable[CollectionChangedEvent], async-selection dispatch
  - Groups: `GroupVM[VM]` (children-as-peers; no Current; retains SelectCommand/DeselectCommand)
  - Aggregates: `AggregateVM1`..`AggregateVM5` fixed-arity tuples
  - Forwarding: `ForwardingComponentVM[M]` + `ForwardingCompositeVM[VM]` decorators
  - Background option dispatches construct/destruct on `Dispatcher.background` scheduler
- 68 conformance tests covering LIFE-001..013, HUB-001..007, PROP-001..004, CMD-001..007, CVM-001..006, COMP-001..011, GRP-001..004, AGG-001..005, FWD-001..003, BLD-001..004, THR-001..004 — all pass.
- 376+ unit tests across all modules — all pass.
- Python 3.10–3.13 supported.
- `mypy --strict` clean across the entire `src/vmx/` tree.
- Examples: `examples/python/hello_vmx/` (console) and `examples/python/tk_todo_app/` (tkinter MVVM).
- Getting-started tutorial at `docs/getting-started/python.md`.
