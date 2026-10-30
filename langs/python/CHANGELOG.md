# Changelog

All notable changes to the Python flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.30.0] — unreleased source version

### Added

- `ExpandableState.expand_command`, `collapse_command` and
  `toggle_expansion_command` (#660, ADR-0159, EXP-006..008). Each command's
  predicate is the matching `can_*` check, its task calls the verb, and its
  `can_execute_changed` fires on every expansion change. The helper builds each
  command on first read and owns it: `dispose()` disposes the commands, which
  are then inert. An owner re-exports a command instead of building one.
- `when_property_changed(hub, sender, property_name, *property_names)` accepts
  further property names: `when_property_changed(hub, chart, "plot", "range")`
  emits each message from `chart` whose property name is any of the names. It
  makes one hub subscription and emits each matching message once, in hub
  order. Pass a sequence as `*names`; a call with no names raises `TypeError`.
  A single-name call behaves as before (spec/03 §7.2, ADR-0160, #664).
- `GroupVMBuilder`, `CompositeVMBuilder` and `CompositeVMOfBuilder` gain
  `destruct_order(order)`, and `GroupVM.create` and `CompositeVM.create` gain
  the `destruct_order` keyword. The new `ChildOrder` enum is exported from
  `vmx`. `ChildOrder.REVERSE` makes `destruct()`, the destruct phase of
  `reconstruct()` and the `dispose()` cascade walk the children from the last
  index to the first. Construct order does not change, and every child is
  still disposed before the container (LIFE-013). The default,
  `ChildOrder.INSERTION`, keeps the current order (#662, ADR-0161, GRP-014,
  COMP-046).
- The child-transition helper is supported API for subclasses of the
  component base. A construct or destruct hook passes the future of
  `_transition_children(children, construct=..., after=...)` to
  `_complete_lifecycle_hook_after`. The walk goes in list order, joins a child
  already in transit, waits for a background child, runs `after` once and
  rolls the parent back when a child fails. Called outside a construct or
  destruct hook, either method raises `RuntimeError` and starts no child. The
  container-only parameters moved to an internal method (#661, ADR-0162,
  LIFE-016, LIFE-017, LIFE-019, LIFE-020).
- `_own_member(member)` registers a member VM and returns it. `dispose()`
  disposes the members in registration order before the parent publishes
  `Disposed`, after a container's own children. Every member is attempted
  and the first failure is raised after the teardown. A member registered
  after `Disposed` is disposed at once. Registering the VM itself raises
  `RuntimeError` (#661, ADR-0162, LIFE-018).
- `TreeSelection[TVM]` in `vmx.hierarchical` and `vmx` holds one current node
  of the materialized tree under a root node (#667, ADR-0164, spec/18 §10,
  HIER-033..HIER-040). It exposes `current`, `can_select(node)`,
  `select(node)`, `clear()`, `current_changed` and `dispose()`. `select`
  raises `ValueError` for a node that `can_select` rejects. The helper watches
  the hubs of the path from the current node to the root, and it clears the
  selection when that node leaves the tree: removal, a transfer out, an
  ancestor's cache invalidation, or disposal. A move inside the tree keeps the
  selection. The helper publishes nothing to a hub and never materializes or
  changes a node. `dispose()` releases the subscriptions and completes the
  stream without emitting.

### Fixed

- `CompositeVM`, `CompositeVMOf` and `GroupVM` `dispose()` now dispose the
  `on_collection_changed` subject when a completion observer raises, then
  re-raise that error. Before, a later subscriber received completion instead
  of `DisposedException` (#1072).
- `CompositeVM.append`/`add`/`insert` and `GroupVM.add`/`insert` re-raise a
  failed parent-transfer commit before a raising destination subscriber's
  error, as the indexer and population paths do (#727). Before, the
  destination error propagated and the commit error was lost. The add still
  publishes one local event and one hub message (#1054).
- `CompositeVM.append`/`add`/`insert`/`__setitem__` and `GroupVM.add`/
  `insert`/`__setitem__` raise `ValueError` for a `None` child and leave the
  children unchanged. Before, they raised `AttributeError` after they opened
  the membership transaction and never closed it. Every later membership
  change then raised `RuntimeError`, and a `dispose()` from another thread did
  not return. Another value without a `status`, such as a slice assignment,
  now also fails without leaving the transaction open (#1048).
- The `AsyncRelayCommand.execute` docstring now says that `execute()` admits
  the run before it returns and schedules it on the running event loop, or on
  the VMx background loop when none runs, without calling `execute_async`.
  Before, it said that `execute()` schedules `execute_async` (#792).
- `ObservableDictionary`: an entry added from a `keys1` subscriber no longer
  puts `keys2` out of first-appearance order. `keys2` now updates first, so a
  `keys1` subscriber already sees the new key2. When a `keys2` subscriber
  changes the entries, the new key1 goes to its first-appearance position in
  `keys1` (#772).
- `ExpandableState.dispose()`, `DiscriminatorVM.dispose()` and
  `PagedComposition.dispose()` now dispose their subject when a completion
  observer raises, then re-raise that error. Before, a later subscriber
  received `on_completed` instead of `DisposedException`.
  `PagedComposition.dispose()` also re-raises the first source-subscription
  disposal error instead of discarding it, after it runs every step (#768).
- The `eager_children` documentation on `HierarchicalVM` and
  `HierarchicalVMBuilder.eager_children()` no longer claims the entire subtree.
  The option applies to this node's children only. It continues deeper only
  through children that are eager themselves (#759, ADR-0156).
- A `CompositeVM`, `GroupVM` or aggregate disposed while its child walk
  waits for a background child no longer publishes a rollback status before
  `DISPOSED`. Before, with a foreground that runs work inline, `construct()`
  then `dispose()` published `CONSTRUCTING`, `DESTRUCTED`, `DISPOSED`, and
  `destruct()` or `reconstruct()` then `dispose()` published `DESTRUCTING`,
  `CONSTRUCTED`, `DISPOSED`. Disposal now abandons the pending walk before it
  disposes any child, as TypeScript does: the walk is cancelled, and a
  deferred completion publishes no status once disposal has started (#755).
- A container child walk cancelled after its loop check no longer takes a
  further step. Cancelled by the children iterator as it ends, it skips
  `after`; cancelled from inside `after`, it skips the commit step. Before,
  it completed the cancelled walk, which raised and logged
  `InvalidStateError`. Every completion in the walk now checks that the walk
  is not already done (#745).
- With `auto_construct_on_add=True`, a `CompositeVM` or `GroupVM` no longer
  publishes `CONSTRUCTED` while a child that an add started during
  `CONSTRUCTING` still constructs (spec/02 §6, spec/06 §5.1). Before, an add
  that read `CONSTRUCTING` after the construct walk's last scan started its
  child, and nothing waited for it. The walk's start records now stay open
  until its commit step. That step runs under the membership gate: it joins
  any child added since the last scan, then commits the `CONSTRUCTED` state in
  the same gated section. An add therefore either reads `CONSTRUCTING` and is
  joined, or reads `CONSTRUCTED` and follows the add-after-Constructed rule.
  The current selector still runs once. Between the commit step and the
  published `CONSTRUCTED` message, `status` already reads `CONSTRUCTED` while
  the transition is still in flight: `can_construct()`, `can_destruct()` and
  `can_reconstruct()` return `False`, `construct()` raises
  `StatusTransitionError` as during `CONSTRUCTING`, and joins wait until the
  publication starts. The walk tracks visited children by reference, so a
  freed child's id is never mistaken for a new member's (#744).
- With `auto_construct_on_add=True`, a `CompositeVM` or `GroupVM` construct
  walk no longer rolls the container back when it pulls a child that a
  cross-thread add attached but has not started yet (spec/06 §5.1). An add
  that will start its child while the container is `CONSTRUCTING` now
  registers a start record as it attaches the child, and marks it done right
  after its construct attempt, before it emits the collection change. The
  walk never starts a late child: it waits for that attempt, then joins the
  child, so the container reaches `CONSTRUCTED` only after it. If the add's
  construct fails, the add fails and is undone, and the container rolls
  back. The walk skips a late child that no add started. Records belong to
  the walk that was current when the add attached the child, so a failed or
  stale walk never takes or clears another walk's records, and a walk's
  records are dropped when it ends rather than at garbage collection (#743).
- A `CompositeVM` or `GroupVM` `dispose()` from another thread no longer
  cleans its children while the container's admitted `on_construct` or
  `on_destruct` hook still runs (LIFE-015). The child cascade now runs at the
  same hook-lease boundary as the base `dispose()`: the container publishes
  `DISPOSED`, waits for the hook to release its lease (or, on a wait-for
  cycle, defers the whole disposal to that release), and then disposes its
  children depth-first before its own cleanup. In that case the children's
  `DISPOSED` messages now follow the container's. With no foreign hook running,
  hook admission closes and the children are still disposed before the
  container publishes `DISPOSED`.
  A same-thread `dispose()` from inside the hook still runs immediately
  (#742).
- When an `approve_command.can_execute_changed` observer raises during
  approval admission, `FormVM` now raises `can_execute_changed` again after it
  releases the in-flight mark, so observers that saw the admission's `False`
  learn the form is approvable again. The observer's exception still reaches
  the caller, and a failure in the release notification does not replace it
  (#732).
- `AsyncRelayCommand.execute()` and the `FormVM` approve command no longer
  stay busy when their scheduled task is cancelled before its first step.
  The done callback now releases the admission and raises one completion
  `can_execute_changed` (spec/04 §10.2). For `FormVM`, it clears the in-flight
  mark and raises `can_execute_changed` before `approve_errors` receives the
  cancellation (spec/20 §5.3). If the loop task factory raises in
  `execute()`, the error reaches the caller and the command is idle again.
  The `AsyncResourceVM` and `TokenPagedComposition` commands inherit the
  fix (#731).
- A disposed `NotificationVM` or `ConfirmationVM` no longer resolves its
  notification on the hub. `_dismiss` and `_resolve_with` now return once the
  VM is disposed, as the C# and TypeScript resolution paths do (DISP-004).
  Before, a command executed from a teardown observer, or an expiry admitted
  before `dispose()`, still resolved the notification on the hub and
  set `is_resolved` to true (#730).
- A raising `on_collection_changed` subscriber no longer stops the rest of a
  committed change's publication in the `GroupVM` indexer or in the
  `GroupVM`, `CompositeVM` and `CompositeVMOf` population loops. Every local
  event and hub message still goes out, and the first failure re-raises, as
  the `CompositeVM` indexer already did (spec/01 §1.4). Before, `group[i] = x`
  published only `remove`, and a population published only its first `add`
  (#727).
- `_own()` on a `ForwardingComponentVM` or `ForwardingCompositeVM` subclass
  registers the resource on the wrapped component. It raised `AttributeError`
  before. The resource is released, in LIFO order with the wrapped component's
  other resources, when that component is disposed through any decorator or
  directly, and at once if it is already disposed (`FWD-005`, ADR-0151, spec
  3.30.0) (#650).

## [3.29.0] — unreleased source version

### Added

- The keyword-only constructors default `hint` to `""`, as the builders do
  (spec/10 §4): the component base, `ComponentVM`, `ComponentVMOf`,
  `ReadonlyComponentVMOf`, the composite base, `CompositeVM`, `CompositeVMOf`,
  `GroupVM`, and `AggregateVM1` to `AggregateVM6`. `ComponentVMOf` and
  `ReadonlyComponentVMOf` also default `modeled_hinter` to an empty hint, and
  `ComponentVMOf` defaults `on_model_changed` to `None` (#663).

### Changed

- An awaited `execute_async()` on `ConfirmationDecoratorCommand` now completes
  when an asynchronous inner command (one with an awaitable `execute_async`, or
  a nested confirmation wrapper) finishes, not when it starts. After a true
  confirmation the decorator invokes the inner exactly once through its
  awaitable entry point, and an inner failure reaches the awaiter instead of the
  inner's `errors`. The fire-and-forget `execute()` still starts an asynchronous
  inner through the inner's own `execute()`, so its failures stay on the inner's
  `errors`; the decorator's `errors` carries only confirmation failures and
  synchronous-inner failures. The decorator adds no admission, cancellation, or
  ownership of the inner (`CMDD-014..017`, ADR-0145, spec 3.29.0) (#355).

### Fixed

- `_own` returns the type of the resource it receives, so
  `self.command: RelayCommand = self._own(...)` type-checks under
  `mypy --strict`. Before, the return type was the union of accepted shapes
  (spec/02 §2.3) (#652).
- An aggregate slot factory that returns `None` makes `construct()` raise
  `ValueError` before any slot is committed. Before, the aggregate constructed
  with an empty slot, which spec/08 §2 calls invalid.
- `AsyncRelayCommand.execute()` admits the run before it returns, so
  `is_executing` is `True` at once, the execution-started `can_execute_changed`
  fires at once, and a following `cancel()` cancels the run. The predicate now
  runs on the caller's thread. If a start-event observer raises, `execute()`
  releases the admission, so the command does not stay executing.
  Before, admission waited one event-loop turn and such a `cancel()` did
  nothing (spec/04 §10.2).
- A `ForwardingComponentVM` around a background component can be a
  factory-populated child: the composite joins it through the wrapped VM.
  Before, construct raised `AttributeError`.
- A `ForwardingCompositeVM` can now be added to a composite or group. Before
  this fix, `add` raised `AttributeError: _ownership_identity`. The decorator
  now shares one ownership identity and its parent link with the composite it
  wraps, as `ForwardingComponentVM` does. Selecting it sets `is_current`, and
  adding either the decorator or the wrapped composite to another container
  moves it out of the old one (spec/09 §1-2, FWD-002/FWD-004).

- A lifecycle hook that defers completion and then raises abandons that
  deferral. The next transition starts clean instead of staying in the
  transient state or raising "a lifecycle hook already deferred completion",
  and the abandoned child transition never runs its continuation. A future
  the hook supplied is dropped, not cancelled; VMx cancels only the child walks
  it created.
- `CompositeVM`, `GroupVM`, `AggregateVM*`, and `HierarchicalVM` wait for a
  background child in any position, including the last. The container
  publishes its terminal status after every child settles, and it rolls back
  when the last child fails to construct or destruct (spec/02 §6, LIFE-014).
  Before, a synchronous child that settled inline let the child walk finish
  early, so the container ignored a background child after it.
- A joined factory child is now checked and joined under its lifecycle lock.
  A child that settles between the check and the join is never started again,
  so its construct hook runs once.
- `CompositeVM` and `GroupVM` with auto-construct-on-add construct a child
  added while the container is still `Constructing` (waiting on a background
  child) and wait for it before reaching `Constructed` (spec/02 §6, spec/06
  §5.1). The child walk joins such a child like a population child, so one
  that fails while the walk waits on it rolls the container back and its hook
  runs once. Before, the add skipped auto-construction until the container was
  `Constructed` and the walk used a snapshot taken before the add, so the
  container reached `Constructed` with the added child still `Destructed`.
- `CompositeVM` and `GroupVM` join the background children that factory
  population starts and never construct them again. A later child that fails
  while the container waits on an earlier one rolls the container back, and
  its construct hook runs once (spec/02 §6, LIFE-014). Before, the child walk
  restarted the failed child and ran its hook a second time.
- `FilteredCompositeVM.set_predicate` restores the previous predicate when the
  new one raises, so later source changes keep using the working predicate. A
  raising `on_changed` observer does not roll the predicate back.
- `FormVM.set_model(None)` raises `ValueError` to the caller during an
  approval's settlement, instead of being queued and surfacing later from
  `approve_async`.
- `CompositeVM.copy_to` validates the index and the target size before writing,
  like `List<T>.CopyTo`; a negative index no longer wraps silently.
- `ForwardingCompositeVM` delegates the rest of the wrapped composite's
  surface: `snapshot`, `subscribe_membership`, `__delitem__`, `append`,
  `index`, `copy_to`, `current_child`, `select_child`, `deselect_child`, and
  `supports_child_selection`. A forwarder can now be the source of an
  `AggregateChangeStream`, as in TypeScript (spec/09, FWD-001).
- A `bool` index raises `TypeError` before any mutation. Before, `True` and
  `False` were taken as `1` and `0` and appeared as indices in
  collection-changed payloads. The check covers `insert`, item assignment,
  `move`, and `remove_at`/`del` on `CompositeVM`, `GroupVM`,
  `ServicedObservableCollection`, and `KeyedServicedObservableCollection`;
  `replace` on the serviced collections; and `insert`, `remove_at`, and
  `replace` on `ObservableList`.
- A slice delete or assignment that selects nothing and inserts nothing on
  `ServicedObservableCollection` or `KeyedServicedObservableCollection` emits
  nothing, instead of a Reset, as TypeScript `splice` does (spec/21 §2.10).
- `ObservableDictionary` key views use dictionary-key equality (identity, then
  `==`), so one `NaN` key object appears once in `keys1`/`keys2`, and
  `nan in view` is true (spec/21 §4.1).
- `walk`, `walk_expanded`, and `find` accept and return the public
  `ComponentVMProto` instead of the private `_ComponentVMBase`, so a caller
  typed against the public protocol passes `mypy --strict` (spec/13 §4).
- `CompositeVM.create()` and `GroupVM.create()` without `children` raise
  `BuilderValidationError`, as `build()` does, instead of a `TypeError`
  (BLD-006, ADR-0055).
- `ConfirmationDecoratorCommand.can_execute` re-checks disposal after the inner
  predicate, which may dispose the wrapper, as the other wrappers do
  (spec/04 §8.4).
- `TokenPagedComposition` stops auto-constructing page items once a hook
  disposes it or starts a newer operation (spec/21 §6).
- A disposed view model's `select` and `deselect` are silent no-ops and
  `can_deselect` returns false, so a disposed child no longer changes its live
  parent's selection (spec/02 §3).
- A disposed `DerivedProperty` rejects writes: `can_set` returns false and
  `set_value` raises instead of running the write-back action (spec/15 §4).
- `ObservableDictionary`: the add index is captured before `keys1`/`keys2`
  update and the local event fires, so a key-view or local subscriber that adds
  another entry no longer shifts the first entry's reported hub index. If such
  a subscriber removes an entry or clears the dictionary, the hub message
  reports the key pair's current index, or -1 when the key pair is gone (#733).
- `CompositeVM.remove`, `remove_at`, `clear`, and item replacement emit
  their collection events even when `on_current_changed` raises, then
  re-raise. Before, the committed change reached no observer.
- Container builders and constructors accept any `MessageHubProto`, as
  component builders do, so `NULL_MESSAGE_HUB` or a custom hub type-checks.
- When a `pending` subscriber disposes the `NotificationHub` and then raises,
  `pending` still completes and its subject is disposed.
- `ObservableList.dispose` and `ObservableDictionary.dispose` complete and
  dispose every stream even when an observer raises, then re-raise the first
  failure.
- The README quick start and getting-started samples type-check under
  `mypy --strict`: the hub is `MessageHub[Message]` and builders name their
  model type.
- `DialogService.present` (the null base) returns the result of a modal that
  was already dismissed, because the first result wins. Before, it returned
  the cancellation result (spec/19 §3, DIA-012).
- `NotificationVM.notify_external_resolve()` is inert after `dispose()`
  (DISP-004).
- `NotificationHub.resolve` and `dispose` complete their waiters even when a
  `pending` subscriber raises. The waiters had already left the hub, so their
  `post` futures stayed pending forever.
- `ConfirmationDecoratorCommand` no longer calls `confirm` when the inner
  command's `can_execute` predicate disposes the decorator (spec/04 §8.4).
- `CompositeVM`, `GroupVM`, `AggregateVM1..6`, `HierarchicalVM`,
  `ForwardingComponentVM`, `ForwardingCompositeVM`, and `AsyncResourceVM`
  now satisfy `IConstructable`, `IDestructable`, and `IReconstructable` in
  `isinstance` checks; only the component classes were registered (spec/14
  rule 2).
- `ObservableDictionary` raises `TypeError` for a `None` key in `d[k1, k2]`
  and `(k1, k2) in d`, as every other accessor already did (spec/21 §4.4).
- A cancelled persister on the `approve_command` path is now reported on
  `approve_errors` as `asyncio.CancelledError`. Before, the cancellation reached
  no channel (spec/20 §5.3).

## [3.28.0] — unreleased source version

### Changed

- `FormVM` model updates are failure-atomic. `set_model` and deny run the
  equality comparison, the validators, and (for deny) the snapshotter on the
  candidate before changing anything; if one raises, the exception reaches the
  caller and the model, snapshot, errors, dirty and valid state, and command
  state are unchanged, with no notification. A failure is never turned into a
  validation error. A validator that reads the form's model sees the previous
  model; it receives the candidate as its argument. If a validator disposes the
  form or makes another edit, the interrupted update commits nothing and the
  newest edit stands, while edits from other threads still wait for an update in
  progress (`FORM-035..038`, ADR-0144, spec 3.28.0) (#337).

## [3.27.0] — unreleased source version

### Changed

- `FormVM` admits one approval at a time. While an approval is in flight,
  `approve_command.can_execute()` is false and any other approve call through
  `approve_async()` or `approve_command.execute()` does nothing: it does not
  call the persister, change state, raise, or emit on `on_approved` or
  `approve_errors`. Admission marks the approval in flight and captures the
  model before raising the approve command's can-execute notification once;
  settlement clears the mark first, then publishes `errors_changed` if needed,
  one can-execute notification, and the outcome, so an approval started by an
  outcome observer is admitted. `set_model` and deny are not blocked. A
  double-executed save now persists once; to save again after an in-flight
  approval, await it and approve again (`FORM-031..034`, ADR-0143, spec 3.27.0)
  (#327).

## [3.26.0] — unreleased source version

### Changed

- `CompositeVM`, `CompositeVMOf`, and `GroupVM` publish each local collection
  change to their message hub as a `CollectionChangedMessage` sent by the
  container, after the local `collection_changed` event. A batch publishes one
  `reset` when its outermost scope completes after a change, an ownership
  transfer publishes the old container's `remove` before the new container's
  `add`, and a rejected or rolled-back mutation, a disposed container, or a
  `ForwardingCompositeVM` publishes nothing. Hub transactions defer the
  messages like any other send. A failing local subscriber does not suppress
  the hub message for a committed change; its error is re-raised afterwards
  (`COMP-042..045`, `GRP-012..013`, ADR-0142, spec 3.26.0) (#579).

## [3.25.0] — unreleased source version

### Fixed

- `TokenPagedComposition` refresh keeps `items` and `current_token` describing
  one loaded prefix. A refreshed first page that matches a longer accumulator
  keeps the prior continuation, so the next `load_more_command` no longer
  refetches and duplicates page two. A matching page as long as the accumulator
  adopts the refreshed token, and an empty or terminal first page shorter than
  the accumulator replaces it (`COL-065`, ADR-0136, spec 3.25.0) (#326).
- `SearchableState`, `TokenPagedComposition`, `FilteredCompositeVM`,
  `NotificationVM`, `ConfirmationVM`, and `DerivedProperty` now run every
  teardown step when one raises, such as a completion observer that raises,
  and then re-raise the first failure, as `FormVM` and the component base
  already did. Previously the first failure stopped the rest, and because the
  disposed flag was already set, the remaining subjects, subscriptions, and
  commands leaked for good (#449).

## [3.24.0] — unreleased source version

### Fixed

- Disposed `CompositeCommand`, `DecoratorCommand`, and
  `ConfirmationDecoratorCommand` are now inert: `can_execute()` is false and
  `execute()` runs no inner command, predicate, pre/post action, or confirmation.
  Disposal observed during execution stops further inner work while an admitted
  pre/post pair stays balanced, and a confirmation that resolves after disposal
  runs nothing and emits nothing (`CMDD-011..013`, ADR-0134).

### Documentation

- The Textual recipe seeds its title and status on mount, follows lifecycle
  changes through the VM-local `property_changed` stream instead of hub
  `PropertyChangedMessage`s (which never carry `status`), and hands changes from
  any thread to the App thread with `post_message`. The embedded widget runs in
  the Textual Notes-Showcase tests on a live App (#341).

## [3.23.3] — unreleased source version

### Fixed

- `FormVM` teardown now attempts every owned step — the approval, error, and
  validation channels and both commands — even when a completion observer or
  owned disposable raises, then re-raises the first failure. A teardown deferred
  until an in-progress `set_model` or deny finishes no longer replaces the error
  that mutation is already raising (#336).
- `AsyncResourceVM` settles the current operation when the loader itself ends
  with `asyncio.CancelledError` — raised directly, from cancelling its own task,
  or from a cancelled operation it awaited. State returns to the saved stable
  state, awaiters and commands complete, nothing reaches Error or a command
  error channel, and a superseded loader's cancellation leaves newer work
  untouched (#334).
- `AsyncResourceVM` now performs loader-task cancellation, cancellation-future
  completion, and late-result registration on the operation's asyncio loop while
  preserving synchronous state invalidation. Completion admission, stable-state
  assignment, and each successful result's cleanup ownership are claimed
  atomically, so stale direct and deferred paths cannot publish or clean the same
  acquisition twice, including reference-identical returns (ADR-0133).
- Caller-owned event loops must stop admissions, cancel, and drain resource work
  while the operation loop can still run before closing it. A closed loop cannot
  finish pending work or force its `finally` blocks; terminal results can only be
  reclaimed through the documented best-effort path.

## [3.23.2] — unreleased source version

### Fixed

- `RxDispatcher.asyncio()` and the Textual adapter use RxPY's
  `AsyncIOThreadSafeScheduler` for foreground delivery from background
  lifecycle workers. The caller stops admissions and awaits admitted work while
  the loop remains responsive, then disposes its VMs and subscriptions and
  explicitly shuts down the independent background pool (ADR-0132).

## [3.23.1](https://github.com/thekaveh/VMx/compare/python-v3.23.0...python-v3.23.1) (2026-08-17)


### Documentation

* **python:** reconcile public 3.23.0 release ([#217](https://github.com/thekaveh/VMx/issues/217)) ([#295](https://github.com/thekaveh/VMx/issues/295)) ([b97e424](https://github.com/thekaveh/VMx/commit/b97e424e7c57b345bbc50c9e446360f90236fe0c))

## [3.23.0] — 2026-07-25

### Added

- `DiscriminatorVM` now exposes `modal_depth` and `clear_modals()` for explicit
  modal-history ownership (`DISC-007/008`, ADR-0128).

### Changed

- A public non-modal `set_active_key` releases every saved modal frame,
  including for a same-key notification no-op, while modal close preserves
  nested LIFO restoration (`DISC-009`, ADR-0128).

### Fixed

- `AsyncRelayCommand` now preserves the first cancellation channel, so an
  externally cancelled execution remains throwing even if command cancellation
  follows.
- Async-command predicate evaluation now detects an intervening admission,
  preventing a reentrant execution from completing before the outer execution
  is admitted while preserving concurrent predicate evaluation.
- Relay-command predicate disposal now invalidates both ordinary and
  parameterized execution admission.
- Async-command event delivery no longer holds the command state lock, and its
  independent notification and error channels no longer block one another
  across observer callbacks.

## [3.22.1] — 2026-07-23

### Fixed

- Hierarchy child factories now validate their complete snapshot before
  assigning parents, rejecting duplicate, cyclic, or already-parented nodes
  atomically and preserving retryability (HIER-031, ADR-0127).
- Valid factory hydration now clears prewarmed descendant path caches, and
  same-receiver structural re-entry rejects without mutation or messages
  (HIER-031/032, ADR-0127).
- Lazy aggregate reconstruction now reserves every proposed child from
  validation through disposal, assignment, and parent commit, preventing two
  concurrent aggregates or a re-entrant disposal hook from retaining the same
  slot. A factory that returns any currently owned slot is rejected before
  mutation.
- Async-resource disposal now attempts every terminal command step and releases
  its retained value before re-raising the first observer failure (ARES-011).
- Pre-owned and multiply decorated components now retain one canonical,
  transferable container identity (FWD-004, ADR-0124).
- Async-resource loaders now capture the full Python `BaseException` contract
  and register late-value cleanup exactly once; composite/group membership
  admission, transfer rollback, factory population, selection, and disposal
  snapshots now share one transaction boundary so concurrent or re-entrant
  mutation cannot escape cleanup; lifecycle compensation failures are surfaced.
- Lifecycle status observers and future continuations now drain outside the
  per-VM state guard. Ordinary foreign lifecycle calls still wait
  synchronously; only a proven cross-VM wait cycle defers publication.
- Membership commits now recheck destination disposal after auto-construction,
  and competing current assignments serialize through the membership gate so
  exactly one retained child remains current.
- CI now verifies Python 3.14 and audits the locked runtime dependency export.
- Built distributions now include the repository's byte-identical Apache-2.0
  `LICENSE` and `NOTICE` files and declare them through PEP 639 metadata.
- Python releases now pin the isolated Hatchling backend and install/smoke the
  exact local wheel before the irreversible PyPI upload.
- Common VM options factories now retain a supplied hub or dispatcher
  independently, so builder validation identifies the actual missing service
  counterpart (BLD-006, ADR-0112).
- Cross-hub sends, disposal, and batches now escape only actual thread wait
  cycles; unrelated busy targets still wait for synchronous calling-thread
  delivery, while cyclic batches borrow the target queue until their body exits.
- Message-hub disposal now serializes stream completion behind an active
  delivery, including reentrant disposal, so every current subscriber observes
  the in-flight message before its terminal notification.
- Cycle-breaking disposal of a batched message hub now claims deferred stream
  completion when the outermost batch exits, even when no drainer was active.
- Token pagination now treats reentrant disposal during page comparison,
  child construction, or reset notification as terminal without committing
  losing state or publishing through disposed subjects.
- Command and component disposal now attempts every terminal notification,
  subscription release, stream teardown, and owned command before rethrowing the
  first observer failure.

## [3.22.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Changed

- The existing best-effort disposal cascade is now part of the normative
  cross-flavor contract (LIFE-013, ADR-0108).

## [3.21.0] — 2026-07-14

Implements `spec-v3.21.0` with 395/395 library conformance IDs covered.

### Changed

- Components now have one authoritative owning parent. Mutable composite and
  group attachment transfers ownership atomically; fixed aggregate slots reject
  transfers, duplicate identities, and ownership cycles (COMP-038..041,
  ADR-0107).

### Fixed

- Form reset publication now defers model edits requested by validation
  observers until `on_approved` has observed the pristine committed state.
- Hierarchy cache invalidation now detaches discarded children so retained
  nodes have a truthful parent and can be attached again.
- `AsyncRelayCommand` now restores its execution state when invoking the task
  factory raises before returning an awaitable.
- A newer token-page refresh now supersedes an older in-flight load, preventing
  stale results from being appended after the refreshed first page.
- Container construction, destruction, and reconstruction now wait for
  background-dispatched child lifecycle transitions before the parent settles.
- Synchronous command entry points now schedule coroutine work on a shared
  background loop instead of blocking the caller with `asyncio.run`.

## [3.20.1] — 2026-07-14

Implements `spec-v3.20.1` with 391/391 library conformance IDs covered.

### Fixed

- Lazy composite children roll back a failed factory attempt so a later access
  can retry instead of retaining partial state.
- Component teardown always performs base cleanup after a throwing override,
  and composite, group, and aggregate disposal isolates child failures while
  still disposing every sibling and the parent.
- `ForwardingCompositeVM` now delegates `move` and `batch_update` alongside the
  rest of the mutable composite surface.
- `HierarchicalVM.add_child` rejects cycles and transfers attached children
  atomically (HIER-018, ADR-0105).
- `PagedComposition` snapshots one-shot iterators once so page count and items
  remain consistent, while reiterable sources stay live.
- Tree walking no longer swallows a `TypeError` raised during iteration.

## [3.20.0] — 2026-07-12

Implements `spec-v3.20.0` and keeps Python at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncResourceVM[T]` models one cancellable async value with immutable
  Idle/Loading/Ready/Error state and load, reload, and cancel commands
  (`ARES-001..011`, ADR-0100).

### Changed

- Latest-start-wins admission rejects stale completion, optional retention
  keeps the accepted value visible, and acquisition-based cleanup releases
  discarded, replaced, stale, and terminal values exactly once.

## [3.19.0] — 2026-07-12

Implements `spec-v3.19.0` and keeps Python at full library parity: 380/380
conformance IDs covered.

### Added

- `SearchableState[T]` accepts an optional `source_changes` observable that
  refreshes the current term after source mutations (`SRCH-001..007`,
  ADR-0099).

### Changed

- Source pulses bypass without resetting term debounce, preserve upstream batch
  boundaries and value-equal emissions, isolate signal failure/completion, and
  cancel only the helper-owned subscription on disposal.

## [3.18.0] — 2026-07-12

Implements `spec-v3.18.0` and keeps Python at full library parity: 373/373
conformance IDs covered.

### Added

- `ObservableMembershipSource[T]` and `AggregateChangeStream[T]` follow
  committed membership in composites, groups, and both serviced collection
  families while reporting `initial`, `membership`, `item`, or `batch`
  provenance (`AGCH-001..010`, ADR-0098).
- `for_components` selects standard component property changes; the general
  selector can observe nested local state.

### Changed

- Duplicate occurrences of the same identity share one selected subscription;
  distinct identities each have their own. Explicit nested batches coalesce
  aggregate output, and idempotent disposal detaches only aggregate-owned
  subscriptions without owning source items.

## [3.17.0] — 2026-07-12

Implements `spec-v3.17.0` and keeps Python at full library parity: 363/363
conformance IDs covered.

### Added

- `KeyedServicedObservableCollection[TKey, T]` adds captured-key `get`,
  `contains_key`, `upsert`, and `delete` while retaining the full mutable
  sequence surface and serviced delivery (`COL-056..064`, ADR-0097).
- Duplicate-key validation and final-result preflight make slice assignment,
  `replace_all`, reverse, and indexed rekeying atomic.

### Changed

- Key lookup and present-key upsert use the captured-key index; item lifecycle
  remains caller-owned and external transactions still defer only hub delivery.

## [3.16.0] — 2026-07-12

Implements `spec-v3.16.0` and keeps Python at full library parity: 354/354
conformance IDs covered.

### Added

- `ServicedObservableCollection` adds idiomatic `remove_at`, `replace`,
  snapshot-based `replace_all`, and strict portable `move` operations while
  preserving list-style `remove` and negative indexed-operation behavior
  (`COL-048..055`, ADR-0096).
- Collection-change messages retain `index` and add precise `old_index` /
  `new_index` positions, including a single Move delivered locally before the
  optional hub sees the final state.

### Changed

- Empty clear, empty-to-empty replacement, and same-index move no-ops are
  notification-free; serviced mutations never acquire item lifecycle ownership.

## [3.15.0] — 2026-07-11

Implements `spec-v3.15.0` and keeps Python at full library parity: 346/346
conformance IDs covered.

### Added

- `subscribe_value(...)` observes selected state from one fixed VM through its
  hub, supports default or custom equality and optional immediate delivery,
  reports current/previous values, and returns a `Disposable` teardown handle.
  Re-entrant ordering, batching, disposal, and subscriber failure behavior follow
  the existing hub contract (`SUBV-001..004`, ADR-0095).

## [3.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps Python at full library parity: 342/342
conformance IDs covered.

### Changed

- The declared current/minimum spec line advances to 3.14.0. The Python runtime
  surface is unchanged because ADR-0094 records TypeScript-only message
  predicate ergonomics and adds no language-neutral conformance requirement.

## [3.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps Python at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republish_model()`, which retains model and hint state, skips assignment,
  hinter, and callback work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [3.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps Python at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVM.set_model` now uses model value equality to suppress a no-op
  candidate, then publishes exactly one model `PropertyChangedMessage` after
  model, validation, and approve-command state settle (`FORM-030`, ADR-0092).
- Compatibility: unequal edits are now visible on the configured hub, while a
  distinct value-equal candidate is retained silently instead of replacing the
  live model and rerunning validators.

## [3.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps Python at full library parity: 340/340
conformance IDs covered.

### Changed

- Modeled component assignment returns before equality, retained-state,
  hinting, callback, or notification work after disposal (`DISP-014`,
  ADR-0091). The existing `FormVM.set_model` terminal guard satisfies the same
  contract.

## [3.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps Python at full library parity: 339/339
conformance IDs covered.

### Added

- The component baseline exposes its injected shared `hub` read-only.
- `_ComponentVMBase._own(...)` registers callables or `dispose()` resources for
  exactly-once LIFO terminal cleanup (`DISP-007..013`).

## [3.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps Python at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList.replace_all(...)` snapshots iterable input and emits one
  Reset plus cardinality-dependent `Count` (`COL-040..047`).

## [3.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps Python at full library parity: 324/324
conformance IDs covered.

### Added

- `attach_many(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [3.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps Python at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `reset_on_approved(...)` for declarative post-persist
  reset, including independent snapshots, revalidation, deterministic race
  semantics, and existing approval error routing (`FORM-024..029`).

## [3.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps Python at full library parity: 310/310
conformance IDs covered.

### Added

- `raise_can_execute_changed()` on `RelayCommand`, `RelayCommandOf`, and
  `AsyncRelayCommand`, including exact live, repeated, trigger-additive,
  in-flight, and post-dispose behavior (`CMD-014..019`).

## [3.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps Python at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `VmCollectionProto` and selection-specific
  `SelectableVmCollectionProto` capabilities.
- Atomic identity-preserving `move(from_index, to_index)` with one move event
  and explicit cross-flavor bounds (`COL-032..039`).

## [3.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps Python at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

## [3.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps Python at full library parity: 290/290
conformance IDs covered.

### Added

- Protected-style `_notify_property_changed` for emitting one hub
  `PropertyChangedMessage` followed by one local property-change notification
  (`CVM-007..009`).

### Changed

- Component, modeled-component, composite, aggregate, and flagship Notes
  Showcase emission sites now use the shared dual-channel helper.

## [3.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps Python at full library parity: 287/287
conformance IDs covered.

### Added

- `TransactionalMessageHubProto` and the `with hub.batch():` context manager
  for nested, lossless FIFO transactions (`HUB-008..013`).
- Iterative re-entrant delivery, serialized concurrent producers, and a
  debug-only publish-cycle diagnostic that reports involved message types.

### Changed

- `NullMessageHub` executes transaction bodies while continuing to publish
  nothing.

## [3.1.0] — 2026-07-01

Implements `spec-v3.1.0` and keeps Python at full library parity: 281/281
conformance IDs covered.

### Added

- `RelayCommand` / `RelayCommandOf` disposed-state inertness (`CMD-013`).
- `TokenPagedComposition`, filtered/scored composite views, declarative
  `FormVM` validation, VM-backed modal presentation, hierarchical child-cache
  invalidation, and `DiscriminatorVM`.

### Changed

- Clarified serviced collection ownership and per-instance property-change
  surfaces in docs/spec comments.
- Pinned existing common options-factory behavior (`BLD-006`) and group-child
  non-selection behavior (`GRP-011`) in conformance coverage.

### Fixed

- Lifecycle operation entry now serializes the status read, in-flight claim, and
  first transient status write under the per-VM lock, preventing a racing
  `dispose()` from winning before `construct()`/`destruct()` enters its hook.
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
  (ADR-0052; VMX-081). It remains available as `from vmx.services import null_message_hub_of` for the narrow-typing case; the package root now offers a
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

- **python:** RELEASING URL-validation checklist + bootstrap tag-ordering gotcha + PyPI badge ([#24](https://github.com/thekaveh/VMx/issues/24)) ([cef3629](https://github.com/thekaveh/VMx/commit/cef3629d623e694350989754c225de1a9c27f909))

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
