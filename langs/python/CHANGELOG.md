# Changelog

All notable changes to the Python flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] — 2026-05-28

Implements spec v2.1.0. Purely additive — no breaking changes from v2.0.x.

### Added

- **`HierarchicalVM`** (`vmx.hierarchical`) — first-class recursive tree VM with
  lazy/eager child loading, depth-first construction, materialized path,
  parent-change and structural-change hub messages. `TreeStructureChangedMessage`
  new type. (ADR-0028; HIER-001..014)
- **`IDialogService`** + **`NullDialogService`** (`vmx.services`) — host-side
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
  composition implementing `IPageable`. (ADR-0023; COL-016..021)
- **`IFilterable`** + **`IPageable`** (`vmx.capabilities`) — two new capability
  protocols. (ADR-0022, ADR-0023; CAP-021, CAP-022)
- **Fluent command helpers** (`vmx.commands`) — `confirm(…)`, `precede_with`,
  `succeed_with`, `wrap_with` extension helpers over commands. (ADR-0027;
  CMD-008..011)
- **`property_value_changed_messages_for`** helper (`vmx.properties`) —
  convenience wrapper for `PropertyValueChangedMessage` sequences. (ADR-0032;
  informative)
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
