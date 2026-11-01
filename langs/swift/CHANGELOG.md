# Changelog — VMx (Swift)

All notable changes to the Swift flavor of VMx are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `TreeSelection<TModel, TVM>`, an opt-in helper that tracks one current
  node per hierarchical tree (#667, ADR-0164, HIER-033..HIER-040). Construct
  it on a root node. `canSelect(_:)` walks only `parent` links and `status`,
  so it never invokes a children factory. `select(_:)` throws
  `TreeSelectionError.notInTree` for a node outside the root's materialized
  tree or on a disposed path, and `clear()` drops the selection.
  `currentChanged` is a hot `AnyPublisher<TVM?, Never>` that emits once per
  effective change, in order. The helper watches the hubs of the nodes on the path from
  the current node to the root. It clears the selection when the node leaves
  the tree through removal, a transfer out, an ancestor's
  `invalidateChildren()` or disposal, and it keeps the selection across a
  move inside the tree. It publishes nothing to a hub, never changes a node,
  and holds the root weakly. `dispose()` releases the hub subscriptions,
  sets `current` to `nil` without emitting, and completes the stream.
- A supported child-transition helper and depth-first member disposal on
  `ComponentVMBase` (#661, ADR-0162, LIFE-016..LIFE-020). A subclass in
  another module calls `try _transitionChildren(children, construct:, after:)`
  from its `_onConstruct()` or `_onDestruct()` override, including the phases
  of `reconstruct()` and a background hook. The helper walks the children in
  the given order, joins a child already in transit, waits for a background
  child, rolls the parent back when a child fails, and runs `after` once
  before the parent publishes its terminal status. Outside the VM's own hook
  it throws `ChildTransitionError`, which is now public, and starts no child.
  `@discardableResult ownMember(_:)` registers a member VM: `dispose()`
  disposes the members in registration order before the parent publishes
  `Disposed`, and a member registered after disposal started (including
  during a container's child cascade) is disposed at once. While the cascade
  runs, a further `dispose()` of the VM, on the same thread or another one,
  returns at once; `AggregateVM1`..`AggregateVM6` now follow the same rule
  for their component cascade. Swift disposal does not throw, so every member is attempted and a
  failing member is not reported. Registering the VM itself traps. The
  container-only walk (late children, population joins) stays internal as
  `_transitionContainerChildren`.
- `ExpandableState.expandCommand`, `collapseCommand` and
  `toggleExpansionCommand` (#660, ADR-0159, EXP-006..008). Each command's
  predicate is the matching `can*` check, its task calls the verb, and its
  `canExecuteChanged` fires on every expansion change. The helper builds each
  command on first read and owns it: `dispose()` disposes the commands, which
  are then inert. The command closures hold the helper weakly.
- `MessageHubProtocol.whenPropertyChanged(_:_:_:_:)` takes two or more
  property names: `hub.whenPropertyChanged(chart, "plot", "range")` emits each
  message from `chart` whose property name is any of the names. It makes one
  hub subscription and emits each matching message once, in hub order. A
  one-name call still binds to `whenPropertyChanged(_:_:)`, and a call without
  names does not compile (spec/03 §7.2, ADR-0160, #664).
- `ChildOrder` and an opt-in reverse child order for container teardown
  (#662, ADR-0161, GRP-014, COMP-046). `.destructOrder(.reverse)` on the
  `GroupVM`, `CompositeVM` and `CompositeVMOf` builders, or
  `destructOrder: .reverse` in `GroupVMOptions` and `CompositeVMOptions`,
  makes `destruct()`, the destruct phase of `reconstruct()` and the
  `dispose()` cascade walk the children from the last one to the first. A
  background child is waited for in that order. Construct order does not
  change, and every child is still disposed before the container publishes
  `.disposed` (LIFE-013). The default, `.insertion`, keeps today's order.

### Fixed

- A `CompositeVM` or `GroupVM` `dispose()` from another thread no longer
  disposes its children while the container's admitted `onConstruct` or
  `onDestruct` hook runs (#1062, LIFE-015). The child cascade and the members
  registered with `ownMember` now run at the hook-lease boundary of the base
  `dispose()`. A leaf's members wait for its admitted hook in the same way. The
  container publishes `.disposed` and waits for the hook to release its lease.
  Then it disposes its children in `destructOrder` and then its members, before
  `_onDispose()`. On a wait-for cycle, the hook's release runs this cleanup.
  With no foreign hook running, the children are still disposed before the
  container publishes `.disposed` (LIFE-013). No hook of the container is
  admitted while that cascade runs. A same-thread `dispose()` from inside the
  hook still disposes the children at once. A child walk whose owner is disposed
  starts no further child and does not run `after`.
- Doc comments now match the code (#791). `CollectionChangedMessage.senderName`
  says that `CompositeVM` and `GroupVM` messages carry the container's `name`,
  and `senderObject` names the container as a possible sender.
  The `DerivedProperty` header, `DerivedPropertyError.cannotSet` and
  `dispose()` docs say that a disposed property rejects writes.
- `ObservableDictionary`: an entry added from a `keys1` subscriber no longer
  puts `keys2` out of first-appearance order. `keys2` now updates first, so a
  `keys1` subscriber already sees the new key2. When a `keys2` subscriber
  changes the entries, the new key1 goes to its first-appearance position in
  `keys1` (#772).
- The `eagerChildren` documentation on `HierarchicalVM` and
  `HierarchicalVMBuilder.eagerChildren(_:)` no longer claims the child subtree.
  The option applies to this node's children only. It continues deeper only
  through children that are eager themselves (#759, ADR-0156).
- `ConfirmationVM.dispose()` runs the base teardown before it disposes
  `approveCommand` and `rejectCommand`. An observer of a command's final
  `canExecuteChanged` value can no longer resolve the hub during disposal
  (#753).
- With `autoConstructOnAdd`, a `CompositeVM` or `GroupVM` no longer
  publishes `.constructed` while a child added during `.constructing` is
  still constructing (#744, spec/02 §6, spec/06 §5.1). Before, an add after
  the construct walk's last late pull started its child and nothing waited
  for it. The walk's start-record scope now stays open until the commit,
  which commits or keeps walking: under the membership gate it joins each
  late child an add registered since the last pull (the current selector
  does not run again), and once none is left it flips the container's state
  to `.constructed` in that same gate section, ends the scope, and only then
  publishes. A later add reads `.constructed` and follows the
  add-after-Constructed rule. A parent walk treats a child container whose
  state is flipped but whose commit is still in flight as still
  constructing. Until that publication starts, `canConstruct()`,
  `canDestruct()` and `canReconstruct()` return `false` and `construct()`
  throws, as during `.constructing`; subscribers of `.constructed` see the
  commit completed. A disposal that cancels the walk during the seal
  publishes no `.destructed` rollback: the finished walk commits
  `.constructed`, then the disposal publishes `.disposed`.
- With `autoConstructOnAdd`, the construct walk of a `CompositeVM` or
  `GroupVM` no longer rolls the container back when it pulls a child that a
  cross-thread add attached but has not started yet (#743, spec/06 §5.1).
  Before, the walk found that child `destructed` and failed with "did not
  reach constructed". An add that attaches a child while the container is
  `constructing` now registers a start record under the membership gate, and
  marks it done right after its construct attempt, before it publishes the
  change. The walk never starts a late child: it waits until the record is
  done, then joins the child. If that construct fails, the add fails and is
  undone, and the container rolls back. A late child that no add starts is
  skipped. An add no longer starts a child that it attached before the walk's
  snapshot, since the walk constructs that child. Start records belong to one
  walk: each walk begins its own scope with its snapshot, takes and drops only
  that scope's records, and never touches a later walk's records. An add that
  attaches after the walk's last pull keeps no record.
- A container no longer refuses an add, a removal or a selection because of
  a stale membership wait edge (#736). Before, a waiter kept its edge until it
  woke and ended its wait, so the thread that had just ended the transaction
  could see a cycle that no longer existed. The shared wait-for graph from
  #703 removes the edges on a transaction before it wakes the waiters; new
  regression tests hold a woken waiter before its own `endWait` and check
  `addResult`, `remove`, `selectChild` and `setCurrent` on composites and
  `addResult` on groups, with a composite or a group releasing the waiter.
- `GroupVM` `remove`, `removeAt` and `clear` now wait for another thread's
  open membership transaction and then apply, as `CompositeVM` does (#728).
  Before, they did nothing while any transaction was open, and `remove`
  returned `false` for a member. A call on the thread that holds the
  transaction, a wait that would close a cycle, or a disposed group still
  leaves the group unchanged. The removal is now published inside the
  group's transaction, as an add already is, so a `collectionChanged`
  handler that changes the group on the same thread during a removal is
  refused (spec/06 §4.2).
- Adding a container beneath a parented `ForwardingCompositeVM`, directly, in
  a nested group, or in an aggregate slot, is now rejected as a cycle when
  that container is the decorator's parent (#724, COMP-039). The ancestor
  walk climbs through the decorator's parent, which the decorator and the
  wrapped composite share as one ownership identity (spec/09 §1-2). Before,
  the add succeeded, and a later `construct()` stalled and `walk` crashed.
- A cross-thread `CompositeVM` or `GroupVM` `dispose()` no longer deadlocks
  when the transaction owner it waits for already waits for the disposing
  thread, with no hub involved (#717, ADR-0153). The disposal records its
  intent, and the owner disposes the container when its transaction ends.
  The shared wait-for graph from #703 detects the cycle; regression tests
  cover composites, groups, and a disposal without a cycle.
- `CompositeVM` no longer traps when the construct walk assigns the
  initial-current selector's pick (#705). The walk checks the pick against
  live membership, so a pick that has left is a silent no-op, as spec/06
  §3.2 requires. A walk that resumes on a thread holding the composite's
  membership transaction joins that transaction instead of trapping, so a
  contained pick still becomes `current`, as in C#.
- `FormVM` no longer deadlocks when an approval raises `canExecuteChanged`
  while `setModel` or deny raises it on another thread, and a sink calls
  `canExecute()` (#704). Top-level `setModel` and deny calls now send
  `errorsChanged` and `canExecuteChanged` after they release the state gate,
  as approval admission and settlement already did (ADR-0143). `setModel`
  sends both, and deny sends `errorsChanged`, inside the approval
  publication scope, so another thread's update or disposal still waits for
  them, and `errorsChanged` values keep commit order. The strict-mode
  approval predicate calls `equals` after it releases the gate.
- `CompositeVM` and `GroupVM` no longer deadlock when a thread that sends on
  the hub inside a membership transaction waits for another thread's hub
  drain, and that drain waits for the transaction (#703). Hub waits,
  membership-transaction waits, container `dispose()` waits, lifecycle
  publication waits and lifecycle hook-lease waits now register in one
  process-wide wait-for graph, so the wait that would close the cycle takes
  its escape instead (spec/03, ADR-0119). Each wait names the hub, container,
  publication or hook lease it waits on, and the thread that frees it removes
  those waits before it wakes the waiters. So a hub drain, hub batch or
  membership transaction that has ended causes no refusal. On a cycle, the hub
  enqueues the send or borrows the batch. `addResult`, `insertResult` and
  `replaceResult` fail with `attachmentFailed`. `remove` returns `false`, and
  `removeAt` and `clear` do nothing. `selectChild`, `deselectChild`,
  `setCurrent`, the `current` setter, `selectComponent` and
  `deselectComponent` leave `current` unchanged. `dispose()` records its
  intent and returns, and the transaction owner disposes the container when
  its transaction ends.
- `CompositeVM` selection made while another thread has the composite's
  membership transaction open (an add, insert, replace, population or another
  selection) now waits for that transaction and then applies (COMP-026,
  ADR-0118). Before, `selectChild` and `deselectChild` silently did nothing,
  `setCurrent`, `selectComponent` and `deselectComponent` threw
  `CompositeMembershipError`, `canSetCurrent` and `canSelectComponent` returned
  `false`, and the `current` setter trapped. Only a transaction opened by the
  calling thread still rejects selection. While it waits, a selection no longer
  holds the shared cross-composite coordinator, so the other thread's hooks
  and callbacks can still select in any composite.

- `HierarchicalVM` `addChild`, `reparentChild`, and `attachMany` report invalid
  lazy children-factory output as an error instead of trapping (spec/18 §6).
  `addChild` returns `.failure`, `reparentChild` throws the error, and
  `attachMany` records an `attachmentFailed` rejection and continues the batch.
  `removeChild` also returns `.failure(.invalidFactoryOutput)` (#737). The
  `children` accessor and `isLeaf` still trap on such output, and so do
  `walk`, `walkExpanded` and `find`, which read `children`.

- A user object whose `deinit` calls back into the VMx primitive that drops
  it no longer deadlocks or traps. `MessageHub` releases delivered and dropped
  messages after its gate unlocks (drain and `dispose()`, HUB-010/HUB-012).
  `propertyChanged` subscription cancellation releases the subscriber after the
  subject's lock. `TokenPagedComposition` releases replaced items and tokens
  after its state queue in `refresh()` and `loadMore()` (COL-065).
  `AggregateChangeStream` releases discarded staged emissions after its staging
  lock, and `dispose()` releases its entries, staged emissions and membership
  subscription after its gate. Before, a message whose `deinit` sent on the hub, a subscriber whose
  `deinit` subscribed again, or an item or token whose `deinit` read the
  composition re-entered a non-recursive lock on the same thread.

- A VM wrapped by a parented `ForwardingComponentVM` or
  `ForwardingCompositeVM` now selects through the decorator's parent:
  `canSelect()`, `select()`, `canDeselect()`, `deselect()`, and the select and
  deselect commands on the wrapped VM select or deselect the decorator, also
  through a decorator of a decorator. The decorator's `selectCommand` and
  `deselectCommand` are now always the wrapped VM's commands (spec/09 §1,
  FWD-001).

- `ForwardingCompositeVM` held by a parent now reports `isCurrent` while it
  is the parent's current child, and selects and deselects through that
  parent. The decorator and its wrapped composite now share one ownership
  identity, so adding the wrapped composite to another container moves the
  decorator out of its old one (spec/09 §1-2, FWD-002/FWD-004).

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
- `CompositeVM`, `GroupVM`, and `AggregateVM1` to `AggregateVM6` wait for
  background children to settle (spec/02 §6). `construct()` reaches
  Constructed, and the composite's current selector runs, only after every
  child is Constructed. `destruct()` reaches Destructed only after every child
  is Destructed. `reconstruct()` waits for both phases. A background child
  that fails rolls the container back (LIFE-014). Disposing a container while
  it waits publishes no further status. Before, the container committed while
  background children were still Constructing or Destructing, and stayed
  Constructed when one failed. Children that settle synchronously keep the
  container synchronous, with unchanged emission order.
- A disposed `CompositeCommand`, `DecoratorCommand`, or
  `ConfirmationDecoratorCommand` stops forwarding inner `canExecuteChanged`
  emissions. Disposal releases the wrapper's inner subscriptions, notifies once,
  and completes the wrapper's own stream, as a disposed `RelayCommand` does; a
  later subscriber receives only completion. The inner streams stay open. Before,
  the stream was the live inner publisher, so it kept emitting and never
  completed (spec/04 §8.4).
- A parented `ForwardingComponentVM.canDeselect()` no longer requires the
  wrapped VM to be constructed. It follows spec/05 §6 (not disposed, parented,
  the parent's current child), so a selected, destructed forwarding child can be
  deselected and its `deselectCommand` is enabled, in agreement with
  `deselect()`.
- `BatchUpdateHandle` has a public `init(endBatch:)`, so a `VMCollection`
  implemented outside the module can return one from `batchUpdate()`, as the
  public protocol requires (spec/01 §1.4).
- Code outside the module can now create an `ObservableList` (`public init()`),
  call `dismiss()` and `resolveWith(_:)` on a `NotificationVM` (they are
  `public`, because Swift has no `protected`; C# and TypeScript keep them
  protected), and create `CollectionChangedEvent` values for its own
  `VMCollection`. Before,
  these were internal, unlike C#, Python, and TypeScript (spec/21 §3.1, spec/16).
- `AsyncRelayCommand.execute()` admits the run before it returns, so
  `isExecuting` is true and `canExecute()` is false straight after the call,
  as in the other flavors (spec/04 §10.2).
- An eager `HierarchicalVM.construct()` throws
  `HierarchyError.invalidFactoryOutput` and rolls back when the children
  factory returns invalid output. Before, it trapped (LIFE-014, ADR-0053).
- `TokenPagedComposition` stops auto-constructing page items once a hook
  disposes it or starts a newer operation (spec/21 §6).
- `ConfirmationDecoratorCommand.canExecute` re-checks disposal after the inner
  predicate, which may dispose the wrapper, as the other wrappers do
  (spec/04 §8.4).
- A disposed `ForwardingComponentVM` no longer changes its parent's
  selection: its `select()`/`deselect()` overrides honor disposal like the
  base (spec/02 §3).
- A disposed `DerivedProperty` rejects writes: `canSet` returns false and
  `setValue` throws instead of running the write-back action (spec/15 §4).
- A disposed `NotificationVM` no longer resolves the hub from `onExpire()`
  or `dismiss()` (DISP-004).
- A disposed `GroupVM` ignores `remove`, `removeAt`, and `clear`, and a
  disposed `CompositeVM` or `GroupVM` throws from `move`, as the disposal
  contract states. Before, they still changed the children.
- A disposed `FilteredCompositeVM` ignores `setPredicate`, `setCurrent`, and
  the visible navigation methods, so it stays frozen as the disposal contract
  states (DISP-006).
- `ObservableDictionary`: the add index is captured before `keys1`/`keys2`
  update and the local event fires, so a key-view or local subscriber that adds
  another entry no longer shifts the first entry's reported hub index. If such
  a subscriber deletes an entry or clears the dictionary, the hub message
  reports the key pair's current index, or -1 when the key pair is gone (#733).
- `HierarchicalVM` caches its path with weak references. Before, the cached
  `[root, …, self]` array retained the node and its ancestors, so a tree that
  had been read through `path` or `addChild` never deallocated.
- `CompositeVM` and `GroupVM` complete `collectionChanged` when disposed.
- `VirtualTimeScheduler.schedule(at:_:)` is no longer `@discardableResult`:
  releasing the returned token cancels the action, so discarding it now warns.
- The default `DialogService.present` returns the result of a modal that was
  already dismissed, because the first result wins. Before, it returned the
  cancellation result (spec/19 §3, DIA-012).
- `HierarchicalVM.removeChild` on a node whose children are not loaded yet
  now runs the children factory first, as the other flavors do. Before, it
  returned without loading the children. `removeChild` now returns a
  `@discardableResult Result<Void, HierarchyError>`, as `addChild` does: invalid
  factory output returns `.failure(.invalidFactoryOutput)` and changes nothing,
  and a later valid factory call still loads the children (#737).

## [3.31.0] — unreleased source version

### Changed

- Implements spec 3.30.0. Forwarding decorators already registered owned
  resources on the wrapped component; `FWD-005` now covers it, including
  nested decorators and registration after disposal (ADR-0151) (#650).

## [3.30.0] — unreleased source version

### Changed

- `ConfirmationDecoratorCommand`'s fire-and-forget `execute()` now starts an
  `AsyncCommand` inner through the inner's own `execute()`, so the inner's
  failure arrives on the inner's `errors` instead of the decorator's, matching
  the other flavors. `executeAsync()` also awaits a nested
  `ConfirmationDecoratorCommand` end to end, invoking every inner exactly once,
  and an awaited inner failure reaches only the awaiter (`CMDD-014..017`,
  ADR-0145, spec 3.29.0) (#355).

## [3.29.0] — unreleased source version

### Changed

- `FormVM` model updates prepare before they commit. `setModel` and deny compute
  the next model, errors, and dirty and valid state from the candidate before
  installing anything, so a validator that reads the form sees the previous
  model and no observer ever sees a new model with old errors. Swift validators,
  `equals`, and the snapshotter cannot throw, so the failure half of the rule
  does not apply. If a validator disposes the form or makes another edit, the
  interrupted update commits nothing and the newest edit stands, while edits
  from other threads still wait for an update in progress (`FORM-035..038`,
  ADR-0144, spec 3.28.0) (#337).

## [3.28.0] — unreleased source version

### Changed

- `FormVM` admits one approval at a time. While an approval is in flight,
  `approveCommand.canExecute()` is false and any other approve call through
  `approveAsync()` or `approveCommand.execute()` does nothing: it does not call
  the persister, change state, raise, or emit on `onApproved` or
  `approveErrors`. Admission marks the approval in flight and captures the model
  before raising `approveCommand.canExecuteChanged` once; settlement clears the
  mark first, then publishes `errorsChanged` if needed, one can-execute
  notification, and the outcome, so an approval started by an outcome observer
  is admitted. `setModel` and deny are not blocked. A double-executed save now
  persists once; to save again after an in-flight approval, await it and approve
  again (`FORM-031..034`, ADR-0143, spec 3.27.0) (#327).

## [3.27.0] — unreleased source version

### Changed

- `CompositeVM` and `GroupVM` publish each local `collectionChanged` event to
  their message hub as a `CollectionChangedMessage<ComponentVMBase>` sent by the
  container, whatever its `Child` type. A batch publishes one `.reset` when its
  outermost scope completes after a change, an ownership transfer publishes the
  old container's `.remove` before the new container's `.add`, and a rejected
  or rolled-back mutation, a disposed container, or a `ForwardingCompositeVM`
  publishes nothing. Hub transactions defer the messages like any other send
  (`COMP-042..045`, `GRP-012..013`, ADR-0142, spec 3.26.0) (#579).

## [3.26.0] — unreleased source version

### Fixed

- `TokenPagedComposition` refresh keeps `items` and `currentToken` describing
  one loaded prefix. A refreshed first page that matches a longer accumulator
  keeps the prior continuation, so the next `loadMoreCommand` no longer
  refetches and duplicates page two. A matching page as long as the accumulator
  adopts the refreshed token, and an empty or terminal first page shorter than
  the accumulator replaces it (`COL-065`, ADR-0136, spec 3.25.0) (#326).
- `FormVM` publishes an approval (`errorsChanged`, the approve command's
  can-execute change, and `onApproved`) without holding its state lock, as the
  C# and Python flavors do. Before, an `onApproved` observer that sent on a
  `MessageHub` while another thread drained it could deadlock with a
  subscriber that read the form. Mutations and disposal on other threads still
  wait until the publication ends (#533).
- `CompositeVM` and `GroupVM` wait for another thread's open membership
  transaction instead of throwing `attachmentFailed`. Before, a population that
  moved a child out of a container whose own population was still finishing
  could fail. A second transaction on the same thread is still rejected, and so
  is a wait that would close a cycle, so opposing populations fail instead of
  deadlocking (#551). Among the other flavors, only C# `GroupVMBase` also waits.
  A C# composite, Python and Rust reject a transaction that another thread
  holds (open cross-flavor decisions ledger §2.10, #756).

## [3.25.0] — unreleased source version

### Added

- `PagedComposition.dispose()` now deterministically detaches an observed
  composite source and completes its property-change publisher.

### Fixed

- Disposed `CompositeCommand`, `DecoratorCommand`, and
  `ConfirmationDecoratorCommand` are now inert: `canExecute()` is false and
  `execute()` runs no inner command, predicate, pre/post action, or confirmation.
  Disposal observed during execution stops further inner work while an admitted
  pre/post pair stays balanced, and a confirmation that resolves after disposal
  runs nothing and emits nothing (`CMDD-011..013`, ADR-0134).
- `ExpandableState` now retains its final value and rejects expand, collapse,
  and toggle mutations after disposal, matching the other flavors.
- `PagedComposition.pageCount` and `items` no longer overflow and trap for very
  large page sizes such as `Int.max`; the page count is computed as
  `1 + (count - 1) / pageSize` and the slice end from the remaining length
  (#354).

### Documentation

- The SwiftUI integration recipe no longer disposes its view model on
  `.onDisappear`, which broke any view that reappeared. Its adapter now states an
  ownership policy: an owned view model is constructed once and disposed exactly
  once when SwiftUI releases the adapter, and a borrowed one is never
  constructed or disposed by the view. Construction failures are published
  instead of discarded, and Save runs a supplied command rather than
  `selectCommand`. `SwiftUIRecipeTests` compiles and runs the exact snippet
  (#340).

## [3.24.0] — 2026-07-25

### Added

- `DiscriminatorVM` now exposes `modalDepth` and `clearModals()` for explicit
  modal-history ownership (`DISC-007/008`, ADR-0128).

### Changed

- A public non-modal `setActiveKey` releases every saved modal frame, including
  for a same-key notification no-op, while modal close preserves nested LIFO
  restoration (`DISC-009`, ADR-0128).

### Fixed

- `AsyncRelayCommand` now preserves the first cancellation channel, so later
  command cancellation cannot hide an externally cancelled parent task.
- Async-command predicate evaluation now reserves admission, preventing a
  reentrant execution from completing before the outer execution is admitted.
- Relay-command predicate disposal now invalidates both ordinary and
  parameterized execution admission.
- A taskless async command is now a true no-op and does not emit transient
  execution-state notifications.

## [3.23.0] — 2026-07-23

### Added

- Added the fallible `tryChildren()` accessor for reporting invalid lazy
  factory output without trapping.

### Fixed

- Hierarchy child factories now validate their complete snapshot before
  assigning parents. `tryChildren()` reports duplicate, cyclic, or
  already-parented output without mutation and permits retry (HIER-031,
  ADR-0127).
- Factory hydration now clears prewarmed path caches for every attached
  descendant and rejects same-receiver structural re-entry atomically
  (HIER-031/032, ADR-0127).

- Lazy aggregate reconstruction now reserves every proposed child from
  validation through disposal, assignment, and parent commit, preventing two
  concurrent aggregates or a re-entrant disposal hook from retaining the same
  slot. A factory that returns any currently owned slot is rejected before
  mutation.
- Pre-owned and multiply decorated components now retain one canonical,
  transferable container identity (FWD-004, ADR-0124).
- Async-resource loading now revalidates its admitted operation after loading
  cleanup, replacement cleanup, and loading notification, so a cleanup callback
  that starts a newer reload cannot publish a superseded completion.
  Composite/group membership admission,
  transfer rollback, factory population, selection, and disposal snapshots now
  share one transaction boundary, preventing concurrent or re-entrant work from
  escaping cleanup and surfacing failed lifecycle compensation.

- Lifecycle publication waits remain synchronous for ordinary foreign calls
  and escape only proven cross-VM wait cycles; selection mutation and removal
  now finish under the same membership gate so concurrent assignments retain
  exactly one current child.

- `ForwardingCompositeVM.subscribeMembership` now observes the wrapped
  composite instead of the decorator's empty inherited collection.

- Token pagination now runs page comparison and child construction outside its
  state queue, then rejects commits and later notifications when either callback
  disposes the pager reentrantly.

- Common VM options factories now retain each independently supplied service
  through the builder's combined services validation (BLD-006, ADR-0112).

- Swift's complete strict-concurrency diagnostics are now enforced in CI.
  Internally spawned tasks and dispatch closures use narrow transfer boundaries,
  immutable singleton services declare their sendability, and modal results are
  constrained to `Sendable` before crossing an async continuation.

- The Notes Showcase now awaits foreground-dispatched UI mutations, publishes
  notifications without blocking commands on user resolution, rejects stale
  overlapping note fetches, uses the library `DefaultDispatcher`, and passes
  the same strict-concurrency CI gate.

- `BasicModalVM` now atomically registers waiters and claims its first dismissal,
  preventing concurrent dismissal/disposal from losing or resuming a waiter
  more than once.

- `MessageHub` invokes subscriber and completion callbacks outside its state
  condition and uses cycle-aware cross-hub waits: unrelated foreign producers
  retain synchronous calling-thread delivery, while only actual dependency
  cycles defer sends, disposal, or borrowed batch work.

- `MessageHub.dispose()` now waits for ordinary foreign batches and transfers
  cycle-breaking completion to the outermost owner boundary, preventing early
  or permanently missing terminal notifications.

- `NotificationHub.pending` now registers subscriber state under its lock but
  attaches downstream afterward, so `CurrentValueSubject` initial replay cannot
  run user code while holding the hub lock.

- `VirtualTimeScheduler` now claims cancellation and execution atomically,
  keeps its clock monotonic when overdue work runs, and retains work scheduled
  through Combine's `Void`-returning overloads until advancement.

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
