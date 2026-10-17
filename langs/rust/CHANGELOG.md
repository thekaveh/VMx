# Changelog — VMx (Rust)

All notable changes to the Rust flavor of VMx are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.35.0] — unreleased source version

### Added

- `DiscriminatorVm::active_key_changes()`, a `ValueStream<K>` that carries the
  new active key with each effective change, as DISC-002 requires. The
  existing `active_changed()` hub still signals changes but carries no key.
  The key stream publishes before the hub, so a hub subscriber that changes
  the key again leaves the stream on the active key.
- `ConfirmationVm::dismiss()`, `dismiss_command()`, `notification()`,
  `remaining_time_ms()`, `opacity()`, and `advance_by_ms()`. Dismissing a
  confirmation resolves it with `Approve`, and its lifespan expiring leaves it
  pending (spec/16 §7).
- `ObservableMultiDictionary::add()`, which rejects an existing key pair,
  `clear()`, which publishes one `Reset` (also when empty, as in every
  flavor), and `entries()`, an insertion-ordered snapshot (spec/21 §4). COL-010..012, COL-014, COL-015, and COL-022 now
  exercise the two-key dictionary instead of the single-key one.
- `Command::as_async()`, a provided trait method that returns a command's
  awaitable entry point, or `None` for a synchronous command. Calling it makes
  one execution attempt whose `AsyncValue` settles when the attempt completes;
  an attempt the command does not admit settles `Ok(())` at once.
  `AsyncRelayCommand` and `ConfirmationDecoratorCommand` provide it, and
  `Arc<T>` forwards it (ADR-0145) (#355).

### Changed

- An awaited `ConfirmationDecoratorCommand::execute_async()` now completes when
  an asynchronous inner command's operation finishes, invoking it exactly once
  through `as_async()`; a nested confirmation is awaited end to end. An inner
  failure reaches the awaiter instead of the inner's error stream:
  `ConfirmationExecution::join()` returns it as `Err(Box<VmxError>)`, which
  downcasts to the original error, and the decorator's `as_async()` entry point
  returns it as `Err(VmxError)`. The fire-and-forget `execute()` is unchanged
  (`CMDD-014..017`, ADR-0145, spec 3.29.0) (#355).

### Fixed

- `CompositeVm` and `GroupVm` membership for `AggregateChangeStream` now comes
  from a local children stream that precedes the hub and is not deferred by a
  hub batch. Before, a member added and changed inside `hub.batch` lost its
  first item change (AGCH-002). A membership pulse now arrives inside the
  container's ownership transaction in a hub batch too, so an observer that
  mutates the container from that pulse gets
  `Err(OwnershipTransactionInProgress)`, as it already did outside a batch.
- A panic in a fire-and-forget `AsyncRelayCommand::execute()` run reaches
  `error_stream()` as `VmxError::Other("command panicked: …")`, as for
  `ConfirmationDecoratorCommand` (spec/04 §10.4, ADR-0137). Before, it was
  lost on the worker thread.
- `FilteredCompositeVm::current()` reconciles the selection when the source's
  membership changed since the last reconciliation, so a current item that
  the source removed or cleared follows the cursor policy (COMP-032,
  COMP-033). An explicit `set_current(None)` stays cleared until the next
  source change. `move_next_visible()` after such a removal now starts from
  the reconciled item, as in the subscribed flavors.
- `CompositeVm` and `GroupVm` collection and `Count` messages carry the
  container's name as `sender_name` instead of `"ObservableList"` (ADR-0120).
- An `AsyncRelayCommand` built with `trigger(...)` and dropped without
  `dispose()` is freed. Its trigger subscription captured a full clone of the
  command, so the trigger hub kept the command and its task alive. This also
  freed a dropped `TokenPagedComposition`.
- `DerivedProperty::recompute` releases the value lock before it runs the
  transform, so a transform that reads `value()` no longer deadlocks.
- A disposed `FilteredCompositeVm` ignores `set_predicate`, `set_current`,
  `set_cursor_policy`, `refresh`, `refresh_scores`, and the visible navigation
  methods, so it stays frozen as the disposal contract states (DISP-006).
  `dispose()` first applies an unread source change, and the cursor policy
  when the predicate now hides the current item, so the frozen current item
  is a member of the frozen projection.
- A disposed `CompositeVm` or `GroupVm` returns `Err(VmxError::Disposed)` from
  `remove`, `remove_at`, and the selection methods, and `clear()` does
  nothing, as `add`, `insert`, and `replace` already did (and `move_item`
  now does, see below). An
  async selection queued before `dispose()` does not run afterwards.
- `FormVm` validators registered after `dispose()` are inactive, as the type
  documentation states; before, they revalidated the disposed form.
- A disposed view model ignores `expand`, `collapse`, and
  `toggle_expansion` (disposal contract).
- An approval subscription disposed by an earlier subscriber during the same
  emission releases its captured state at once, not at the end of the
  emission (ADR-0139).
- `NotificationHub` keeps pending notifications in post order. Before, it
  ordered them by creation identity (spec/16 §2.1).
- `NotificationVm::is_resolved` reports a hub-side resolve that used the
  `Pending` reaction (NOTIF-015). Hub disposal neither resolves nor
  unresolves the VM.
- `CompositeVm::move_item` and `GroupVm::move_item` return
  `Err(VmxError::Disposed)` after disposal instead of reordering the children.
- A disposal deferred behind an admitted lifecycle hook (same-thread or
  cyclic) now disposes the commands of `ComponentVm`, `CompositeVm`,
  `GroupVm`, and `AggregateVm1..6` only after the hook, owned resources, and
  streams finish, as on the immediate path (spec/02 §2.4, §7). A second,
  concurrent disposer also leaves them to the thread that completes the
  disposal.
- `FormVm::approve()` no longer calls the persister when an approve-command
  `can_execute_changed` handler disposes the form during admission. The
  approval is refused and its in-flight mark is cleared (spec/20 §5.3).
- `ModalVm` keeps its first result: `open()` no longer re-arms a dismissed
  modal, so a later `dismiss` cannot replace the stored result. The claim and
  the stored result now share one lock, so `is_dismissed()` never reports a
  dismissal before `result()` holds it (DIA-012).
- An eager `HierarchicalVm::construct()` now cascades into its children inside
  its own Constructing phase. A disposed or already-constructed parent
  constructs no child, a lazy factory failure returns an error instead of
  panicking, and the parent's Constructing message precedes its children's
  (spec/18 §3).

## [0.34.0] — unreleased source version

### Changed

- `FormVm` model updates are failure-atomic. `set_model` and deny run the
  equality comparison, the validators, and (for deny) the snapshotter on owned
  copies before changing anything; a panic in one of them unwinds to the caller
  with the model, snapshot, errors, dirty and valid state, and command state
  unchanged, no notification, and no lock poisoned or held. A failure is never
  turned into a validation error, and a panicking validator fails `build()`. A
  validator that reads the form sees the previous model. Updates are serialized
  per form by a re-entrant update lock, so another thread's edit, approval
  commit, or disposal waits for an update in progress; if a validator itself
  disposes the form or makes another edit, the interrupted update commits
  nothing and the newest edit stands (`FORM-035..038`, ADR-0144, spec 3.28.0)
  (#337).

### Fixed

- A same-thread re-entrant `execute()` on a `RelayCommand` or
  `RelayCommandOf<T>` no longer deadlocks. The command held its action's mutex
  while running it, so a nested call from the action, a `can_execute_changed`
  handler, or a hub subscriber (for example an `approve_command().execute()`
  from FormVM's approved callback, `approve_errors` subscriber, or settlement
  notification) blocked forever. Built-in commands now run a nested call inline,
  as the other flavors do. A command built from a user `FnMut` action defers an
  admitted nested call until its current action returns, still before the
  outermost `execute` returns; a call from another thread waits, a deferred call
  does not run after disposal, and a panicking action drops the calls deferred
  during it. Built-in commands called from several threads now run concurrently,
  like the methods they wrap.

## [0.33.0] — unreleased source version

### Changed

- `FormVm` admits one approval at a time. While an approval is in flight, the
  approve command's `can_execute()` is false and any other approve call through
  `approve()` or the approve command does nothing: it does not call the
  persister, change state, return an error, or emit on the approved callbacks or
  `approve_errors`. Admission marks the approval in flight and captures the
  model before raising its can-execute notification once; settlement clears the
  mark first, then publishes errors-changed if needed, one can-execute
  notification, and the outcome, so an approval started by an outcome observer
  is admitted. `set_model` and deny are not blocked. A double-executed save now
  persists once; to save again, approve after the in-flight approval returns
  (`FORM-031..034`, ADR-0143, spec 3.27.0) (#327).
- A panic in the persister or the reset settles the approval like a failure
  (the mark is cleared and one can-execute notification is raised) before the
  panic resumes on the caller (#327).

## [0.32.0] — unreleased source version

### Fixed

- A disposed `CompositeVm` or `GroupVm` no longer publishes collection changes.
  Removals, moves, clears, and a batch still open at disposal published
  `CollectionChanged` and `PropertyChanged("Count")` messages after `dispose()`;
  publication now stops when disposal starts. A disposal deferred by an
  in-progress membership transaction still publishes that transaction's
  committed changes first. The other flavors now publish container changes on
  the hub as Rust already did (`COMP-042..045`, `GRP-012..013`, ADR-0142, spec
  3.26.0) (#579).

## [0.31.0] — unreleased source version

### Added

- `MessageHub::record(capacity)` returns a `MessageRecorder` that keeps the
  newest `capacity` messages the hub accepts, records them at acceptance in
  delivery order, and counts evicted messages in `dropped()`. It never changes
  delivery, never keeps its hub alive, and stops recording when dropped,
  disposed, or when its hub is disposed (ADR-0141, #325).
- `FormVm::subscribe_approved` returns an `ApprovalSubscription`. Disposing or
  dropping it detaches that approval callback and releases its captures before
  the form is disposed, and `is_active()` reports whether it still receives
  approvals (ADR-0139, #357).
- `AsyncValuePanic`, with `AsyncValue::wait_result()` and
  `AsyncValue::try_result()`, reports the panic of the `map` or `and_then`
  callback that produced a handle (ADR-0138, #339).
- `CommandErrorStream`, returned by `AsyncRelayCommand::error_stream()` and
  `ConfirmationDecoratorCommand::error_stream()`, delivers each fire-and-forget
  failure once as the original `VmxError`. It is hot, isolates subscriber
  panics, and completes on disposal. An awaited `execute_async` still returns
  the failure and publishes nothing, and cancellation never appears. A panic
  caught by the confirmation decorator arrives as `VmxError::Other` carrying the
  panic message; `execute_async().join()` still returns the payload itself
  (ADR-0137, #330).

### Changed

- `MessageHub` no longer retains accepted messages. Before, every hub, including
  the private hubs inside commands, forms, collections, paging, and
  notifications, kept every message ever sent, even after disposal. Attach a
  `MessageRecorder` before the sends you need to inspect (ADR-0141, #325).
- `AsyncRelayCommand::execute()` starts no worker thread for a rejected call:
  no action, an execution already running, a false predicate, or a disposed
  command. `execute_async()` still returns `JoinHandle<VmxResult<()>>`; for a
  rejected call that handle comes from a short-lived thread and completes with
  `Ok(())`. `TokenPagedComposition::refresh()` and `load_next()` start no
  thread when their command rejects the call (ADR-0140, #356).
- An awaited `AsyncResourceVm` load blocks until its loader reports or the load
  is cancelled, superseded, or disposed, instead of polling every millisecond.
  Cancellation still completes the load at once while an uncooperative loader
  keeps running, and the loader's late value is still cleaned once
  (ADR-0140, #356).
- An approval callback registered after `FormVm::dispose()` is dropped at once
  instead of being retained, and a callback detached during an approval before
  its turn does not receive it (ADR-0139, #357).
- A panicking `AsyncValue::map` or `and_then` callback now settles the returned
  handle as panicked instead of leaving it pending forever. The panic propagates
  through compositions, every waker and other continuation still runs, `wait()`
  and `.await` re-raise it, and `try_get()` returns `None`.
  `ConfirmationDecoratorCommand::execute_async().join()` returns a panicked
  confirmation's payload instead of blocking, and fire-and-forget `execute`
  publishes it on `error_stream()` (ADR-0138, #339).

### Deprecated

- `MessageHub::history()`, which is now always empty; record with
  `MessageHub::record(capacity)` and read `MessageRecorder::messages()` (#325).
- `FormVm::on_approved`, which cannot be detached before the form is disposed;
  use `subscribe_approved()` (#357).
- `AsyncRelayCommand::errors()` and `ConfirmationDecoratorCommand::errors()`,
  whose `Message::Custom { name: "error" }` marker carries no cause. They still
  announce every failure; use `error_stream()` (#330).

### Fixed

- `TokenPagedComposition` refresh keeps `items()` and `current_token()`
  describing one loaded prefix. A refreshed first page that matches a longer
  accumulator keeps the prior continuation, so the next load no longer refetches
  and duplicates page two. A matching page as long as the accumulator adopts the
  refreshed token, and an empty or terminal first page shorter than the
  accumulator replaces it. A load or refresh that finishes after a later one
  started now commits nothing, in both constructor paths and in `load_more`, as
  in the other flavors (`COL-065`, ADR-0136, spec 3.25.0) (#326).

## [0.30.0] — unreleased source version

### Added

- `FormVm::with_clearing_model_validator` and
  `FormVmBuilder::clearing_model_validator` accept model validators returning
  `BTreeMap<String, Option<String>>`: `Some(error)` sets a field error, `None`
  clears an error from a field validator or an earlier model validator, and an
  omitted field keeps its entry. The string-map `with_model_validator` /
  `model_validator` remain as the compatibility path and wrap every entry in
  `Some` (#333).
- `AsyncRelayCommand` implements `Command`, so it can be stored as
  `Arc<dyn Command>` and wrapped by `CompositeCommand`, `DecoratorCommand`, and
  `ConfirmationDecoratorCommand`. The trait methods delegate to the inherent
  ones: `execute` starts fire-and-forget execution without waiting for the body,
  failures are reported once on `errors()`, and eligibility and
  `can_execute_changed` are shared with the inherent surface (#344).
- `CompositeCommand::dispose()` and `DecoratorCommand::dispose()` make the
  wrappers inert; clones share disposal state, as `ConfirmationDecoratorCommand`
  clones already do (ADR-0134).
- A `CommandExt` trait provides `confirm`, `precede_with`, `succeed_with`, and
  `wrap_with` on every `Command + Clone + 'static`, so the wrapper a fluent
  helper returns chains further. `Arc<T: Command + ?Sized>` implements
  `Command`, which lets non-`Clone` commands and `Arc<dyn Command>` use the
  helpers, and `NO_HOOK` / `NO_PREDICATE` make absent `wrap_with` arguments
  usable without type annotations. `RelayCommand`'s inherent helpers remain and
  delegate to the trait (#358).
- `TokenPagedComposition::dispose()` now terminally disables its owned
  load-more and refresh commands and prevents in-flight loaders from committing
  pager state; loader-returned items remain caller-owned.

### Changed

- `TokenPagedComposition` now exposes single-flight `AsyncRelayCommand`s for
  loading and refresh, publishes eligibility changes as token state changes,
  and always starts and refreshes from the canonical initial/terminal `None`
  token. The legacy constructor token argument remains accepted but is ignored.

### Fixed

- A disposed `ConfirmationDecoratorCommand` now reports `can_execute() == false`,
  and disposed composite and decorator wrappers run no inner work, keep an
  admitted pre/post pair balanced, and ignore a confirmation that resolves after
  disposal (`CMDD-011..013`, ADR-0134).
- Refresh deduplication once again compares a fresh first page with the matching
  accumulator head, preserving already accumulated later pages.

## [0.29.0] — 2026-08-03

### Added

- `Dispatcher::dispatch_background`, `DefaultDispatcher`, and independently
  drainable foreground/background `ManualDispatcher` channels.
- `ComponentVmBuilder::background` and options parity for asynchronous
  construct/destruct hooks with foreground terminal publication.
- Mutable and read-only component builders preserve reusable
  `on_construct`/`on_destruct` callbacks alongside background configuration.
- `ReadonlyComponentVmBuilder` background parity and the event-only, hot typed
  `background_errors()` lifecycle-failure stream.

### Fixed

- `THR-002` now exercises genuine background lifecycle work, including
  disposal supersession and foreground rollback publication.
- Synchronous construct/destruct publication completes before return, while
  reconstruction remains a synchronous atomic destruct/construct operation
  even when background hooks are enabled.
- Background rollback delivers its status, original error, and deferred stream
  completion in order under re-entrant disposal.
- Re-entrant disposal from a background hook preserves disposal-hook errors and
  converts disposal panics to a stable typed error before stream completion.
- Rejected background or foreground scheduling restores the prior state instead
  of stranding an in-flight lifecycle; default workers are created before VM
  admission for the same guarantee.
- Synchronous lifecycle panics now roll back before unwinding. Disposal hook
  errors or panics emit one terminal status, finish owned/stream/command cleanup,
  and cannot abort later siblings or parent cleanup in container cascades.

## [0.28.0] — 2026-08-02

### Changed

- **Breaking pre-publication correction:** `AsyncResourceVm<T, D>` now embeds
  the caller's dispatcher, exposes explicit shared-service constructors, and
  uses `status()` for ordinary component lifecycle state. Resource acquisition
  phase is available through `resource_status()` and `state().status()`.

### Fixed

- `AsyncResourceVm` now implements `VmNode` and leaf `TreeNode`, delegates the
  complete model-free component surface, publishes through its injected hub,
  and participates in composite ownership, selection, and atomic reparenting.
- Resource cleanup and command teardown now run only after the embedded
  component has admitted its terminal `Disposed` transition, so reentrant
  callbacks cannot reopen the lifecycle or observe an intermediate status.
  The consumer disposal hook is snapshotted at the same admission boundary,
  preventing command-teardown callbacks from replacing terminal work.

## [0.27.0] — 2026-07-25

### Added

- `DiscriminatorVm` now exposes `modal_depth()` and `clear_modals()` for
  explicit modal-history ownership (`DISC-007/008`, ADR-0128).
- Capability parity now includes predicate-based `Filterable<T>`, the complete
  `Pageable` navigation surface on `PagedComposition`, `Expandable::is_expanded`,
  mutable `Searchable`, and fully constructible/disposable `ExpandableState`.
- The VMx-owned reactive layer now includes typed, replaying, completion-aware
  `ValueStream<T>`; completion-aware message-hub subscriptions; and replaying
  notification pending streams, including immediate empty completion for null
  services.
- `DerivedProperty` now has one- through five-source constructors that own their
  subscriptions, automatically recompute on source changes, suppress equal
  outputs, and stop on disposal.
- `AsyncValue` now supports executor-neutral `map` and `and_then`
  continuations, with deterministic retained-continuation diagnostics.

### Changed

- A public non-modal `set_active_key` releases every saved modal frame,
  including for a same-key notification no-op, while modal close preserves
  nested LIFO restoration (`DISC-009`, ADR-0128).
- Explicit hierarchy reparenting of a detached child reports `Reparented`;
  removing a non-member from a hierarchy, group, or composite is a successful
  no-op; and fixed aggregates publish all populated-slot notifications before
  constructing any child.
- Direct form approval now gates on disposal and validity only. Strict/dirty
  gating remains on approve-command eligibility.
- The complete component VM family now exposes `view_model_type`, including
  groups, composite variants/wrappers, aggregate arities one through six,
  hierarchies, forms, and async-resource VMs. Component options and forwarding
  wrappers preserve or delegate the canonical value.
- **Breaking pre-publication correction:** confirmation-decorator
  `execute_async()` now returns the executor-neutral `ConfirmationExecution`
  future instead of `std::thread::JoinHandle<()>`, eliminating one retained
  operating-system thread per unresolved decision. Inferred `.join()` callers
  retain that call shape; explicitly typed callers must migrate to
  `ConfirmationExecution`, which also supports `.await` and `.is_finished()`.
  It intentionally has no `thread()` accessor because no native worker exists;
  `.join()` preserves the original boxed panic payload for downcasting.

### Fixed

- Expanded tree walking now uses the `Expandable` capability. Disposed
  searchable state reads as an empty term, and explicit search returns empty
  without invoking the item provider or predicate.
- Message, value, and notification streams now serialize value/terminal
  delivery, preserve synchronous resolver-thread continuation semantics, and
  isolate subscriber, continuation, mapper, and waker panics. Opposing
  cross-stream callbacks enqueue without waiting on a foreign drainer, avoiding
  callback cycles while ordinary foreign-thread sends and disposal remain
  synchronous.
- Concurrent multi-source `DerivedProperty` transforms now commit and publish
  through one serialized snapshot-revision stream, preventing an older delayed
  result from overwriting or publishing after the newer latest-at-emission
  value.
- Notification pending snapshots replay in committed order and publish before
  waiter completion. Confirmation helpers and decorators no longer retain one
  native thread per unresolved decision.
- Confirmation-decorator disposal now completes its error channel and guards
  later work. Relay-command disposal emits the optional final
  `can_execute_changed` notification before stream completion.
- Async-command predicate evaluation now reserves admission, preventing a
  reentrant execution from completing before the outer execution is admitted.
- Relay-command predicate disposal now invalidates both ordinary and
  parameterized execution admission without retaining the disposal lock across
  user code.
- The awaitable confirmation-decorator entry point now applies the inner
  eligibility gate before invoking the confirmation delegate.
- A taskless async command is now a true no-op and does not emit transient
  execution-state notifications.

## [0.26.0] — 2026-07-23

### Added

- Added the fallible `try_children()` accessor for reporting invalid lazy
  factory output without panicking.

### Fixed

- Hierarchy child factories now validate and commit their complete snapshot
  under the topology gate. `try_children()` reports duplicate, cyclic, or
  already-parented output without mutation and permits retry (HIER-031,
  ADR-0127).
- Factory hydration now clears prewarmed path caches for every attached
  descendant and rejects same-receiver structural re-entry atomically
  (HIER-031/032, ADR-0127).

- Direct reconstruction now rejects destructed, transient, and disposed VMs as
  required by the lifecycle fixture. The command, message-hub, and lifecycle
  fixture conformance tests now execute and assert every fixture scenario
  instead of merely loading those files beside marker-only examples.
- Fixed aggregates now share the same atomic per-child ownership claim as
  mutable groups and composites, preventing concurrent constructors or lazy
  reconstruction from retaining the same child under two parents. A factory
  that returns a currently owned slot is rejected before mutation. Lazy
  reconstruction also completes every validated slot swap, commits the new
  ownership registry, and publishes each slot change before returning the first
  prior-child disposal failure.
- Forwarding components now delegate the complete component surface, support
  real nested decorator layers and idiomatic hint overrides, and retain one
  canonical transferable container identity (FWD-001/002/004, ADR-0124).
- Composite transfers now finish old-remove and destination-add publication
  before resuming a failing old-current callback (COMP-041).
- Messages now expose the canonical diagnostic `sender_name` alongside Rust's
  ownership-safe `sender_id`, and async-resource replacement cleanup can start
  a newer reload without publishing the superseded completion afterward.
- Component selection now delegates through the owning selectable parent and
  exposes stable baseline commands with automatic lifecycle eligibility
  triggers; lifecycle capabilities apply to every VM node without implicitly
  opting core components into selection or expansion.
- Lifecycle publication and message-hub disposal now remain ordered and
  deadlock-free under opposing callbacks, queued completion versus disposal,
  and re-entrant terminal work. Cross-hub coordination now escapes only actual
  wait cycles and supports borrowed cyclic batches without weakening unrelated
  synchronous delivery.
- Async-resource loading revalidates its admitted operation after cleanup and
  notification. Composite/group admission, transfer rollback, population, and
  disposal snapshots share one transaction guard so concurrent/re-entrant
  mutation cannot escape; selection revalidates at dispatch, replacement
  rollback is identity-safe and non-panicking, and abandoned ownership
  transfers release their claim. Commits recheck destination disposal after
  auto-construction, and failed lifecycle compensation is returned instead of
  being hidden by the initiating population error.
- Packed crates now include the repository's byte-identical Apache-2.0
  `LICENSE` and `NOTICE` files.
- Hierarchy structural messages now include the mutation kind, affected child
  identity, and index, and parent-change notifications use Rust's `parent`
  property spelling.
- Children whose previous weak owner has been dropped can be attached to a new
  composite or group instead of retaining an unusable expired ownership handle.
- Serviced collections now serialize mutation commit with delivery admission,
  so concurrent Add positions publish in committed order without weakening
  same-thread re-entrant delivery or caller-thread hub publication.

## [0.25.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Added

- `AggregateVm1` through `AggregateVm6` now expose immutable builders with
  required lazy component factories, optional pre-construction slots, and the
  common name, hint, reconstruction, selection, and command surface.

### Changed

- Aggregate factories are invoked at construct time and again on reconstruct;
  all candidates are ownership-validated before any previous slot is replaced.
- Aggregate slot accessors now use idiomatic `component_1` through
  `component_6` names and return `Option<T>` because builder-created slots are
  empty before construction. The unnumbered aliases remain available.

### Fixed

- Hierarchical parent links now hold weak state, so dropping an unreachable
  materialized tree releases both parents and descendants without making
  hierarchy disposal own, detach, or dispose child lifetimes.
- Cached form and async-resource commands no longer form owner-retention
  cycles; dropping the VM and its external command handles releases captured
  persisters, loaders, validators, and cleanup resources.
- Modeled components now expose `modeled_hint()` separately from the immutable
  fixed `hint()`, so the builder's default empty fixed hint no longer masks
  model-derived text or causes CVM-004 to test the wrong property.
- Nested sends from one active message-hub callback to another hub now enqueue
  instead of waiting on the foreign drainer, preventing opposing-hub deadlocks
  while ordinary producers retain synchronous calling-thread delivery.
- The published crate now includes the repository's Apache-2.0 license text.

## [0.24.0] — 2026-07-14

Implements `spec-v3.22.0` with 395/395 library conformance IDs covered.

### Fixed

- Terminal disposal now attempts every child and the parent core before
  returning the first failure (LIFE-013, ADR-0108).
- `AggregateVm3` through `AggregateVm6` now expose every typed slot and the
  complete lifecycle, service, ownership, status, equality, and `VmNode`
  surfaces already provided by the lower arities.

## [0.23.0] — 2026-07-14

Implements `spec-v3.21.0` with 395/395 library conformance IDs covered.

### Changed

- `VmNode` parent state is now a real weak owner handle. Mutable composite and
  group attachment transfers ownership atomically; fixed aggregate slots reject
  transfers, duplicate identities, and ownership cycles (COMP-038..041,
  ADR-0107).
- `ReadonlyComponentVm` now exposes the component baseline directly and
  implements `VmNode`/`TreeNode` without revealing its writable inner VM.
- Component hints are construction-time state; the public post-construction
  `set_hint` mutation escape is removed.
- `FormVm` and `FormVmBuilder` now live in a focused forms module while
  retaining their crate-root exports.
- The disposable package consumer now recreates the crate with the committed
  lockfile enforced.

### Fixed

- Form reset publication now defers model edits requested by validation
  observers until approved callbacks have observed the pristine committed state.
- Hierarchy cache invalidation now detaches discarded children so retained
  nodes have a truthful parent and can be attached again.
- Failed lifecycle hooks publish the rolled-back construction status, and a
  failing dispose hook still completes the local property-change stream.
- Form commands are stable handles; form disposal closes commands, channels,
  callbacks, validators, and the underlying component deterministically.
- Model hints, form callbacks, validators, and snapshotters execute without
  holding their backing state locks, allowing safe reentrant reads or updates.
- Concurrent hierarchy materialization invokes its factory once, and
  concurrent reparenting preserves exactly one parent-child membership.

## [0.22.0] — 2026-07-14

Implements `spec-v3.20.1` with 391/391 library conformance IDs covered.

### Added

- `AsyncValue<T>` provides executor-neutral `Future` and blocking completion
  for dialog, notification, modal, and confirmation flows (ADR-0106).
- `make_confirm` adapts the notification hub to an async confirmation gate.

### Changed

- `DialogService`, `ModalVm::completion`, `NotificationWaiter`, and
  `ConfirmationDecoratorCommand` now model genuinely pending interactions.
- `ForwardingCompositeVm` delegates the complete collection and selection
  surface.

### Fixed

- Async-command cancellation cannot be lost during token admission.
- Command predicate panics map to `false` instead of unwinding through callers.
- Hierarchy attachment rejects cycles and transfers attached children without
  duplicating them across parents (HIER-018, ADR-0105).

## [0.21.0] — 2026-07-13

Implements `spec-v3.20.0` and keeps Rust at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncRelayCommandBuilder` now provides `task`, `predicate`, additive
  `trigger`, and opt-in `throw_on_cancel` setters.
- `AsyncRelayCommand::errors()` routes non-cancellation fire-and-forget faults;
  `VmxError::Cancelled` distinguishes the cooperative cancellation result.

### Changed

- Async command admission is atomic, panic-safe teardown always clears the
  in-flight state, default cancellation completes normally, and throwing mode
  returns `VmxError::Cancelled` through the join handle (ADR-0104).
- The Rust reactive primitive is documented and packaged as the directly
  implemented VMx-owned hot-stream facade; the unused `rxrust` and runtime-only
  `serde_json` dependencies are removed (ADR-0103).
- Application examples now commit lockfiles, enforce `--locked` CI execution,
  and declare an MSRV no lower than the library.
- A panicking async-resource loader restores the prior stable state and
  preserves the panic through the public load handle.

## [0.20.0] — 2026-07-12

Implements `spec-v3.20.0` and keeps Rust at full library parity: 391/391
conformance IDs covered.

### Added

- `AsyncResourceVm<T>` models one cancellable async value with immutable
  Idle/Loading/Ready/Error state and load, reload, and cancel commands
  (`ARES-001..011`, ADR-0100).

### Changed

- Latest-start-wins admission rejects stale completion, optional retention
  keeps the accepted value visible, and acquisition-based cleanup releases
  discarded, replaced, stale, and terminal values exactly once.
- Corrected the declared MSRV from Rust 1.82 to 1.88 because the required
  `rxrust` 1.0.0-rc.5 uses edition-2024 let chains: Cargo 1.82 cannot parse its
  manifest and Rust 1.85 cannot compile it.
- Prepared the checked crates.io release channel with a strict package
  allowlist, Rust 1.88/stable consumers, tag/main/version gates, one-time
  bootstrap authentication, trusted-publishing migration, and public
  crates.io/docs.rs verification before release notes.

## [0.19.0] — 2026-07-12

Implements `spec-v3.19.0` and keeps Rust at full library parity: 380/380
conformance IDs covered.

### Added

- `SearchableState::new_with_changes` and `from_items_with_changes` accept a
  `MessageHub` source signal; shared idempotent `dispose()` cancels the owned
  subscription (`SRCH-001..007`, ADR-0099).

### Changed

- Source pulses emit one `filtered_changed` invalidation without suppressing
  equal projections or owning the source/items. Source-hub disposal remains
  isolated from explicit pull search.

## [0.18.0] — 2026-07-12

Implements `spec-v3.18.0` and keeps Rust at full library parity: 373/373
conformance IDs covered.

### Added

- `ObservableMembershipSource<T>` and `AggregateChangeStream<T>` follow
  committed membership in composites, groups, and both serviced collection
  families while reporting `Initial`, `Membership`, `Item`, or `Batch`
  provenance (`AGCH-001..010`, ADR-0098).
- `ObservablePropertySource` enables the `for_components` convenience; the
  general selector accepts custom `PropertyChangedStream` sources.

### Changed

- VM identity refcounts share one selected subscription, explicit nested
  batches coalesce aggregate output, and idempotent disposal detaches only
  aggregate-owned subscriptions without owning source items.

## [0.17.0] — 2026-07-12

Implements `spec-v3.17.0` and keeps Rust at full library parity: 363/363
conformance IDs covered.

### Added

- `KeyedServicedObservableCollection<K, T>` adds captured-key `get_by_key`,
  `contains_key`, `upsert`, and `remove_key` while preserving indexed `get` and
  ordered serviced collection operations (`COL-056..064`, ADR-0097).
- Duplicate-key validation and final-result preflight make whole-list
  replacement and indexed rekeying atomic without requiring cloneable keys.

### Changed

- Key lookup and present-key upsert use the captured-key index; item lifecycle
  remains caller-owned and external transactions still defer only hub delivery.

## [0.16.0] — 2026-07-12

Implements `spec-v3.16.0` and keeps Rust at full library parity: 354/354
conformance IDs covered.

### Added

- A distinct `ServicedObservableCollection<T>` provides local and optional
  external hub delivery for push, first-match value removal, indexed removal,
  replacement, snapshot-based whole-list replacement, move, and clear; it is
  not an alias for `ObservableList<T>` (`COL-001..004`, `COL-048..055`,
  ADR-0096).
- Effective mutations publish the existing non-generic collection message with
  precise optional old/new positions after local observers see final state.

### Changed

- Empty clear, empty-to-empty replacement, and same-index move no-ops are
  notification-free; serviced mutations never acquire item lifecycle ownership.

## [0.15.0] — 2026-07-11

Implements `spec-v3.15.0` and keeps Rust at full library parity: 346/346
conformance IDs covered.

### Added

- `MessageHub::subscribe_value(...)` observes selected state for one fixed sender
  ID, supports `PartialEq` or custom equality and optional immediate delivery,
  reports current/previous values, and returns a `Subscription` teardown handle.
  Re-entrant ordering, batching, unsubscription, and subscriber panic isolation
  follow the existing hub contract (`SUBV-001..004`, ADR-0095).

## [0.14.0] — 2026-07-11

Implements `spec-v3.14.0` and keeps Rust at full library parity: 342/342
conformance IDs covered.

### Changed

- The package line advances to 0.14.0 with minimum spec 3.14.0. The Rust runtime
  surface is unchanged because ADR-0094 records TypeScript-only message
  predicate ergonomics and adds no language-neutral conformance requirement.

## [0.13.0] — 2026-07-11

Implements `spec-v3.13.0` and keeps Rust at full library parity: 342/342
conformance IDs covered.

### Added

- Writable, read-only, and forwarding modeled components expose
  `republish_model()`, which retains model and observable hint state, skips
  assignment and hinter work, and emits one ordinary `"model"` hub/local pair
  (`CVM-010`, ADR-0093).

## [0.12.0] — 2026-07-11

Implements `spec-v3.12.0` and keeps Rust at full library parity: 341/341
conformance IDs covered.

### Changed

- `FormVm::set_model` retains its `PartialEq` no-op gate and now publishes the
  model notification only after validation and approve-command state settle
  (`FORM-030`, ADR-0092).

### Fixed

- Deny now publishes one ordered `FormReverted` + idiomatic `"model"` pair
  instead of the embedded component's early `"model"` plus legacy `"Model"`;
  approval reset no longer leaks a component model notification.

## [0.11.0] — 2026-07-11

Implements `spec-v3.11.0` and keeps Rust at full library parity: 340/340
conformance IDs covered.

### Changed

- `ComponentVm::set_model` returns before equality, retained-state, hinting, or
  notification work after disposal (`DISP-014`, ADR-0091). The existing
  `FormVm::set_model` terminal guard satisfies the same contract.

## [0.10.0] — 2026-07-10

Implements `spec-v3.10.0` and keeps Rust at full library parity: 339/339
conformance IDs covered.

### Added

- `ComponentVm::hub()` exposes the injected shared hub.
- `ComponentVm::own(...)` registers `FnOnce` cleanup for exactly-once LIFO
  terminal cleanup (`DISP-007..013`).

## [0.9.0] — 2026-07-10

Implements `spec-v3.9.0` and keeps Rust at full library parity: 332/332
conformance IDs covered.

### Added

- `ObservableList::replace_all(...)` snapshots iterator input and emits one
  Reset plus cardinality-dependent `Count` (`COL-040..047`).

### Fixed

- `ObservableList::batch_update` now restores nesting after panics and suppresses
  `Count` for count-preserving batches before resuming the original panic.

## [0.8.0] — 2026-07-10

Implements `spec-v3.8.0` and keeps Rust at full library parity: 324/324
conformance IDs covered.

### Added

- `attach_many(...)` with consumer key selectors, stable fixpoint resolution,
  non-replacing deduplication, park/reject orphan policy, structured rejection
  results, and root-owned disposal cleanup (`HIER-023..030`).

## [0.7.0] — 2026-07-10

Implements `spec-v3.7.0` and keeps Rust at full library parity: 316/316
conformance IDs covered.

### Added

- Immutable-builder `reset_on_approved(...)` returning `VmxResult<M>` for
  declarative post-persist reset, including independent snapshots,
  revalidation, deterministic race semantics, and existing approval error
  routing (`FORM-024..029`).

## [0.6.0] — 2026-07-10

Implements `spec-v3.6.0` and keeps Rust at full library parity: 310/310
conformance IDs covered.

### Added

- `raise_can_execute_changed()` on synchronous, parameterized, and async relay
  commands, with the previous `trigger_can_execute_changed()` retained as an
  alias (`CMD-014..019`).
- Async relay execution-start and execution-completion notifications on the
  existing command channel, completing the normative in-flight sequence.

## [0.5.0] — 2026-07-10

Implements `spec-v3.5.0` and keeps Rust at full library parity: 304/304
conformance IDs covered.

### Added

- Shared `VmCollection<T>` and selection-specific
  `SelectableVmCollection<T>` traits.
- Atomic identity-preserving `move_item(from_index, to_index)`, `Move`
  collection actions with both indices, and VM wrapper replacement methods
  (`COL-032..039`).

## [0.4.0] — 2026-07-10

Implements `spec-v3.4.0` and keeps Rust at full library parity: 296/296
conformance IDs covered.

### Added

- Cross-cutting disposal conformance for lifecycle owners, commands, hubs,
  interaction owners, reactive helpers, and collection/projection helpers
  (`DISP-001..006`).
- A public disposal-surface inventory documenting completion, owned teardown,
  post-dispose behavior, and second-call behavior.

### Fixed

- Lifecycle disposal now publishes its terminal `Disposed` transition exactly
  once instead of dispatching the identical intermediate and final state.
- `NotificationHub::dispose` now claims disposal atomically, so racing callers
  cannot complete subscriber snapshots more than once.

## [0.3.0] — 2026-07-10

Implements `spec-v3.3.0` and keeps Rust at full library parity: 290/290
conformance IDs covered.

### Added

- `PropertyChangedStream` and `property_changed` accessors across component,
  container, hierarchy, aggregate, readonly, and forwarding handles provide
  the per-instance local notification surface.
- `ComponentVm::notify_property_changed` emits one hub
  `PropertyChangedMessage` followed by one local notification and becomes
  inert after disposal (`CVM-007..009`).

### Changed

- Internal component-family property setters now use the shared dual-channel
  helper after equality checks and assignment.

## [0.2.0] — 2026-07-10

Implements `spec-v3.2.0` and keeps Rust at full library parity: 287/287
conformance IDs covered.

### Added

- `MessageHub::batch` for nested, lossless FIFO transactions
  (`HUB-008..013`).
- Iterative re-entrant delivery, condition-variable serialization for
  concurrent producers, and a debug-only publish-cycle diagnostic naming
  message variants.

### Changed

- The null hub executes transaction closures while continuing to publish
  nothing.

## [0.1.0] — 2026-07-09

### Added

- Initial full-parity Rust source flavor with behavioral coverage for the 281
  library conformance IDs in `spec-v3.1.0`.
