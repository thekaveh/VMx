# Changelog — VMx (Rust)

All notable changes to the Rust flavor of VMx are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.36.0] — unreleased source version

### Added

- A regression test for a cycle-deferred disposal failure (ADR-0200,
  #1297). Rust already returned the failure from the hook thread's call.
- The `notifications` Cargo feature, which `default` includes (ADR-0211,
  #1264). It gates the notification sub-package of spec/16:
  `NotificationHub`, `NullNotificationHub`, `NotificationHubApi`,
  `make_confirm`, `Notification`, `NotificationType`, `NotificationReaction`,
  `NotificationWaiter`, `NotificationVm` and `ConfirmationVm`. A dependency
  with `default-features = false` builds the core without them. `ModalVm`
  stays in the core.
- The `NotificationHubApi` trait (ADR-0211, #1264). It declares
  `post_notification`, `resolve`, `pending` and `pending_stream`.
  `NotificationHub`, `NullNotificationHub` and `Arc<H>` for every implementer
  `H` implement it, so `Arc<dyn NotificationHubApi>` works.
- `own_member` on `CompositeVm`, `ModeledCompositeVm`, `GroupVm` and
  `AggregateVm1` to `AggregateVm6` (#1289, ADR-0204). It follows the
  `ComponentVm::own_member` contract and rejects the container itself with
  `VmxError::OwnershipCycle`. `dispose()` disposes the children and then the
  registered members, before the container publishes `Disposed`. During a
  foreign dispose the container publishes `Disposed` first and disposes both
  after the hook returns (ADR-0179). A member registered after the disposal
  started is disposed by its registration.
- `CompositeVm::with_destruct_order` and `GroupVm::with_destruct_order`, public
  raw constructors that take a `ChildOrder` (#1287, ADR-0204). `new` and
  `with_services` keep `ChildOrder::Insertion`.
- `COMP-050`, `COMP-051`, `COMP-052` and `LIFE-022` conformance tests
  (ADR-0188, ADR-0189). A refused child `select()` or `deselect()` already
  changed nothing and returned nothing in Rust (`COMP-052`).
- `COL-067` conformance tests (#1176, ADR-0177). A hub subscriber of
  `ObservableMultiDictionary` reads the updated entries, count, `keys1()` and
  `keys2()` snapshots. The tests cover add, insert, remove and clear, and
  mutations that change one key view or none (#1429). Rust already behaved
  this way.
- `COL-066` conformance tests: a panicking local collection subscriber does
  not suppress the hub `CollectionChangedMessage` (#1051, ADR-0171). Rust
  already behaved this way.
- `TreeSelection<M>`, an opt-in helper that keeps one current node for the
  tree under a root `HierarchicalVm` (#667, ADR-0164, `HIER-033`..`HIER-040`).
  `TreeSelection::new(&root)` creates it. `can_select` walks parent links to
  the root and rejects a path with a disposed node, and it never reads
  children. `select` returns `VmxError::InvalidArgument` for a non-member and
  keeps the current node. `clear` clears it, and `current_changed()` is a hot
  `ValueStream` that emits once for every effective change. The helper
  watches the hubs of the path from the current node to the root and clears
  the selection when the node is removed, transferred out of the tree,
  dropped by an ancestor's `invalidate_children`, or disposed, or when an
  ancestor is. A move inside the tree keeps the selection. The helper
  publishes nothing to a hub, never navigates, and never disposes a node.
  Clones share one selection, and the type is `Send + Sync`: its lock is
  never held while it reads the tree, subscribes or emits, and a revision
  counter discards a stale re-check. `dispose()` releases the subscriptions,
  clears without emitting, completes the stream, and is idempotent.
- `ExpandableState::expand_command()`, `collapse_command()` and
  `toggle_expansion_command()`, and an inherent `can_toggle_expansion()`
  (#660, ADR-0159, EXP-006..008). Each command's predicate is the matching
  `can_*` check, its action calls the verb, and the `expanded_changed()` hub
  triggers its `can_execute_changed()`. The state builds each command on first
  read, under a lock, and owns it: every call returns a clone of the same
  command, clones of the state share it, and `dispose()` disposes it, after
  which it is inert.
- `GroupVmBuilder`, `CompositeVmBuilder` and `ModeledCompositeVmBuilder` have
  a `destruct_order(ChildOrder)` setter, and `GroupVmOptions` and
  `CompositeVmOptions` have a `destruct_order` field for `create`. With
  `ChildOrder::Reverse`, `destruct()`, the destruct phase of `reconstruct()`
  and `dispose()` walk the children from the last to the first. The default,
  `ChildOrder::Insertion`, keeps the current order. Construct order does not
  change, and every child is still disposed before its container (ADR-0161,
  `GRP-014`, `COMP-046`) (#662).
- A supported child-transition helper for consumer view-model types that
  compose a `ComponentVm` (#661, ADR-0162, `LIFE-016`..`LIFE-020`).
  `ComponentVm::construct_with_children`, `destruct_with_children` and
  `reconstruct_with_children` run the component's own transition and, after
  its hook, pass a new `ChildTransitions` handle to a walk closure.
  `ChildTransitions::transition` constructs or destructs one member at a time,
  in the order given. It skips a member already at the target and joins one
  already in transit. `ChildTransitions::then` runs a callback before the
  component publishes its terminal status. A background member keeps the
  component transient until it settles, and a failing member or callback rolls
  the component back. The handle borrows the transition, so the compiler
  rejects a use outside the closure.
- `ComponentVm::own_member` registers a member view-model. `dispose()` now
  disposes the registered members in registration order before the component
  publishes `Disposed`, keeps the first failure, and returns it after the
  component's own teardown. A member registered after disposal began is
  disposed at once. Registering the component itself returns
  `VmxError::OwnershipCycle`. While the members are being disposed, any other
  `dispose()` of the component, re-entrant or from another thread, returns
  `Ok(())` at once without waiting, and the first call finishes the work. A
  component with no members disposes as before (#661, ADR-0162, `LIFE-018`).
- The walk methods have two limits (#661, ADR-0162).
  `construct_with_children` and `destruct_with_children` return
  `VmxError::InvalidArgument` for a component built with `background(true)`
  and start no transition, because the walk cannot move to the background
  dispatcher. Members built with `background(true)` still run their hooks in
  the background. `reconstruct_with_children` runs on the calling thread for
  every component, as `reconstruct()` does. `reconstruct()` and
  `reconstruct_command()` run only the component's hooks and never a walk, so
  a consumer type reconstructs through `reconstruct_with_children`.
- `NotificationVm::dispose()` and `ConfirmationVm::dispose()` (#1067,
  ADR-0178, `DISP-004`). Disposal disposes the dismiss, approve and reject
  commands, so a kept command clone reports `can_execute()` false and no
  longer resolves the hub. It does not resolve the notification, stops the
  lifespan clock, and keeps `is_resolved()` at its value at disposal. A first
  reaction stays authoritative, and a second call has no effect. Disposal
  never disposes the hub. Before this change, a kept command still resolved
  the hub after the host dropped the view model.
- `HierarchicalVm<M, N = ()>` takes a node-data type `N`, the Rust form of a
  `TVM` subclass (#1263, ADR-0202). `parent()`, `children()`, `path()`, the
  children factory and `attach_many` use `HierarchicalVm<M, N>`, and
  `node_data()` returns the node's own `N`. `HierarchicalVm::with_node_data`
  and `HierarchicalVmBuilder::with_node_data` create such nodes, and
  `TreeSelection<M, N = ()>` follows the node type. `N` defaults to `()`, so
  code that names `HierarchicalVm<M>` or `TreeSelection<M>` is unchanged.

### Changed

- Breaking: `NullNotificationHub` functions are instance methods that mirror
  `NotificationHub` (ADR-0211, #1264): `new`, `post_notification`, `post`,
  `post_with_waiter`, `resolve` (no effect), `pending` (always empty) and
  `pending_stream`. The type derives `Clone`, `Copy`, `Debug`, `Default`,
  `PartialEq` and `Eq`. Migration: `NullNotificationHub::post(notification)`
  becomes `NullNotificationHub.post_notification(notification)`,
  `NullNotificationHub::pending_stream()` becomes
  `NullNotificationHub.pending_stream()`, and the removed
  `NullNotificationHub::post_message(message)` becomes
  `NullNotificationHub.post_with_waiter(NotificationType::Notification, message)`.
- `make_confirm` accepts any `NotificationHubApi + Clone + 'static` hub, such
  as a `NullNotificationHub`, whose predicate completes with `true` at once
  (ADR-0211, #1264). A `NotificationHub` argument works as before.
- `NotificationHub` keeps no history of committed pending snapshots
  (ADR-0211, #1275). Before, each post, resolve and dispose kept a full copy
  of the pending list for the life of the hub, and `dispose()` did not clear
  them. One pending notification and 100,000 post and resolve pairs kept
  200,001 snapshots.
- The three test-only seams, `vmx::wait_registered_for_testing`,
  `vmx::container_wait_registered_for_testing` and
  `GroupVm::set_last_scan_probe_for_testing`, now need the non-default
  `test-seams` Cargo feature (#1294). A default build no longer exports them.
  The conformance tests that call them run with `--all-features`. This is not
  a breaking change: the seams are hidden test-only API, and no published
  release exported them.
- Breaking: `GroupVmOptions` and `CompositeVmOptions` have a new
  `destruct_order` field, so code that builds them with a struct literal must
  now set it (#662).
- The `reconstruct_command()` of `CompositeVm` and `GroupVm` now calls
  `reconstruct()`, as the aggregates' command does, instead of repeating its
  steps. A later fix to the walk therefore reaches the command too. The
  command now also applies the `reconstruct()` admission check, so a container
  that another thread destructs after the command's `can_execute` check is no
  longer constructed again by the command. The stored command holds its
  command table and its parent registration weakly. A command handle that
  outlives every handle to its container therefore does nothing, and it does
  not keep that container registered as its children's parent (#799).
- `ServicedObservableCollection`, `KeyedServicedObservableCollection`,
  `ObservableDictionary` and `ObservableMultiDictionary` now share one stored
  snapshot between concurrent readers, which run `PartialEq` on it (#765).
  These types are therefore `Send` and `Sync` only when their item and key
  types are `Sync` as well as `Send`. Before, `Send` items and keys were
  enough. `VmNode` types are already `Sync`, so collections of view-models are
  not affected.
- Implements spec 3.30.0. Forwarding decorators already registered owned
  resources on the wrapped component; `FWD-005` now covers it, including
  nested decorators and registration after disposal (ADR-0151) (#650).
- `CompositeVm` selection opens no membership transaction (spec/06 §4.3,
  ADR-0173, #1145). `set_current`, `select_component`, `deselect_component`
  and a child's `select` and `deselect` commit `current` and both current flags
  under the membership gate and publish after it. They no longer return
  `OwnershipTransactionInProgress` because another thread holds a transaction,
  or from the add's own `CollectionChanged` publication, so a subscriber can
  select the child that was just added. On the thread whose own add, insert,
  replacement, population or transfer has not committed, every selection call
  still returns `OwnershipTransactionInProgress`, also `set_current(None)`. A
  child that an add has attached but not admitted returns `NonChild`. While
  disposal is pending, a non-null selection returns `Disposed`, and clearing
  with `None` or `deselect_component` now succeeds. `can_select_component`
  answers whether `select_component` would succeed now, so another thread's
  transaction no longer makes it `false`. With `async_selection`, the call
  validates under the same rules and the delivery validates again. A
  disposal requested on another thread while a selection publishes returns at
  once and runs when the publication ends. The two `COMP-026` tests that were
  ignored for this gap run again.
- `VmNode` has two hidden methods with defaults, `commit_current_flag` and
  `publish_current_flag`. A container commits the current flag under its gate
  and publishes it afterwards, so two concurrent selections leave the flags
  in commit order. Wrapper nodes should forward both methods; the defaults
  keep the old behavior through `set_current_flag`.
- `NotificationVm::dismiss_command()`, `ConfirmationVm::approve_command()`,
  `reject_command()` and `dismiss_command()` return a clone of one command
  that the view model owns, not a new command for each call (#1067,
  ADR-0178). Clones of the view model share the commands. A command holds
  only the shared notification state, so a kept command makes no reference
  cycle.
- Breaking: `TokenPagedComposition` requires
  `Token: Clone + Send + Sync + 'static` and runs `Token::clone` with no pager
  lock held (#1278, ADR-0202). Clones of one stored token no longer take
  turns, and a clone that reads the cursor again on its own thread no longer
  blocks forever. A `Send`-only token, for example one that holds a `Cell`, no
  longer compiles. Wrap its state in a `Mutex` or an atomic.

### Deprecated

- `NotificationHub::pending_snapshots()`, which is now always empty
  (ADR-0211, #1275). Migration: subscribe to `pending_stream()` before the
  posts and resolutions to observe, and collect the values. The first value
  is the snapshot that is current at subscription.

### Fixed

- A current `AsyncResourceVm` loader that ends with its own cancellation now
  restores the saved stable state, as `cancel` does, instead of installing
  `Error` (ADR-0199, spec/23 §7, `ARES-012`, #1353). The cancellation can come
  from any source, such as a shared request that another owner cancels. A
  superseded loader's cancellation changes nothing. The signal is
  `Err(VmxError::Cancelled)`. `load_async` and `reload_async` return after the
  restore is published, as they do after a loader failure.
- `NotificationVm::is_resolved()` and `ConfirmationVm::is_resolved()` no
  longer change from `true` to `false` when `dispose()` races a hub
  `resolve` (ADR-0211, #1293). Both view models now read the hub under their
  flags lock, so `dispose()` reads the hub and sets `disposed` in one critical
  section, and `is_resolved()` returns a hub value only if no disposal
  completed between its `disposed` check and its hub read.
- Breaking: a `CompositeVm` or `GroupVm` from the builder or from
  `create(options)` has no children until its first `construct()` (#1255,
  ADR-0204, spec/06 §1, spec/07 §3). That construct calls the `children`
  factory once, inside the construct transition and after the construct hook,
  as in C# and TypeScript, and attaches the result before the construct walk;
  `build()` no longer calls it. A construct that starts while the factory runs
  fails with `VmxError::ConcurrentOperation`. A refused population, such as
  `VmxError::DuplicateChild`, now fails the first `construct()` instead of
  `build()`: the container publishes `Constructing`, rolls back to
  `Destructed`, attaches nothing and keeps the factory for the next construct.
  A factory that panics also keeps its slot.
- A stored `reconstruct_command()` of `CompositeVm`, `GroupVm` and
  `AggregateVm1` to `AggregateVm6` reports `can_execute()` false once every
  container handle dropped, as in Swift; its `execute()` stays inert (#1483,
  ADR-0204). The aggregate command now holds the parent registration weakly,
  so the children of a dropped aggregate report no parent and can join
  another container while the command handle exists.
- The `FormVm::dispose()` rustdoc now states the deferred-teardown rule
  (#1292). After a refused wait, or while a delivery outside a publication
  scope is in progress, the teardown runs when no publication and no delivery
  remains on any thread, on the thread that ends the last one. Before, the
  rustdoc named the publishing or delivering thread that the disposal found.
  It also lists a validator registration's notifications as a delivery
  outside a scope. A new test keeps deliveries open on two threads and checks
  that the channels complete on the thread whose delivery ends last. The code
  does not change.
- The `FormVm` rustdoc now states the limit of a re-entrant model `Clone`
  (#1279). The form runs `M::clone` under the lock of the live model or the
  snapshot, and these locks are not re-entrant. A model `Clone` that calls a
  method of its own form that reads the model or the snapshot on the same
  thread never returns. Examples are `model()`, `snapshot()`, `is_dirty()`,
  `set_model()`, `approve()`, `revert()` and the approve and deny commands,
  and `can_approve()` in strict mode. A model `Clone` can read `is_valid()`,
  `errors()`, `error_map()` and `field_error()`. The code does not change.
- Disposing the current child of a `CompositeVm` now clears the composite's
  `current` before `dispose()` returns (ADR-0189, #1317). The composite
  publishes the change once and calls `on_current_changed(None)` once. The
  disposed child reads `is_current()` false and publishes no change for it. A
  disposed child can no longer become current: `set_current` returns
  `VmxError::NonChild`. The composite's own dispose cascade does not clear
  `current`.
- A `CompositeVm`, `GroupVm` or fixed-arity aggregate that holds a directly
  disposed child now destructs, constructs and reconstructs (ADR-0189,
  #1383). Container walks and the child-transition helper skip a disposed
  child. A walk that waits for a background child that is disposed meanwhile
  now goes on. Before, every `destruct()` failed with `VmxError::Disposed`
  and the container stayed `Constructed`.
- A non-null selection while a `CompositeVm` is `Destructing` now changes
  nothing and returns `Ok(())` (ADR-0188, #1425). This covers `set_current`,
  `select_component`, the child `select()` path, and an async call and its
  delivery. `can_select_component` returns `false` meanwhile. `destruct()`
  and `reconstruct()` therefore return with no current child, also when
  `on_current_changed`, a child's destruct hook or another thread selects a
  child.
- A `FormVm` call nested in a preparation callback or an `errors_changed`
  subscriber of `set_model` or `revert` now returns before its notifications
  (ADR-0180, spec/20 §5.4, #1173). This covers `set_model`, `revert`,
  `approve()` and the approve command. The outermost update sends them before
  it returns, with no lock held: error maps first, in commit order, then the
  other notifications. A nested `approve()` returns `Ok(())` once admitted,
  and its persister runs after that; a failure goes to `approve_errors`. A
  nested call no longer commits while another thread holds a publication
  scope; it takes the refused-wait result. Queued notifications are dropped
  once the form is disposed.
- `CompositeVm::replace` now clears the replaced child as `current` before it
  frees the child, as `remove_at` does (#1219). Before, the commit freed the
  child first. Another thread could adopt the freed child into another
  composite and select it there. The clear then reset the child's current
  flag while the other composite kept it current (`COMP-006`).
- Every blocking wait between VMx resources now records in one process-wide
  wait-for graph, following ADR-0172 (spec/03 §4.1 and §4.2, spec/02 §2.4,
  `HUB-013`, #1158, #1180, #1183). Hub `send`, `batch` and `dispose` waits,
  a hub drainer's wait for a borrowed scope, a foreign `dispose()` wait for an
  admitted hook, and a container disposal's wait for a membership
  transaction now see one another. So a cross-thread container `dispose()`
  and the owner of that container's transaction no longer hang when they
  wait for each other through a hub drain or a hook, in either order. Each
  resource has a typed, address-derived key. The thread that ends a batch,
  releases a drain, leaves its borrowed scopes, or finishes a hook removes
  the edges that name it before it wakes the waiters. So an ended wait no
  longer makes `batch` borrow a hub, or a foreign `dispose()` defer its
  cleanup to a hook that has returned, and the dispose hook's failure now
  returns from that `dispose()`. A hub records each borrower thread: a
  borrower's own `send` enqueues for the drain at its last borrowed scope's
  exit, its `batch` nests another borrowed scope, and its `dispose` records
  terminal intent. None of them waits for its own borrow. Every wait on a
  borrowed scope records an edge, and a borrower that leaves its last scope
  while others remain wakes the waiters. A drainer whose queue is empty
  releases the drain to the last borrowed scope's exit instead of waiting.
  A drainer with queued messages whose wait would close a cycle also
  releases it, and that exit delivers the queue in FIFO order on the
  borrower's thread, after the drainer's `send` has returned (the documented
  `HUB-010` limitation). A `send` from inside a hub callback no longer skips
  its wait for a borrowed scope, so it stays synchronous unless its wait is
  refused. After a borrower's `dispose`, the last of the batch owner, the
  drainer, and the borrowers to release the hub completes it: a borrower's
  exit no longer completes a hub whose batch is still open, and a drainer
  stops waiting for the borrowed scopes once a disposal is requested (spec/03
  §4.2 rule 3). A borrower's exit also no longer completes the hub while
  another thread's drain is still delivering a message on it; that drain
  completes the hub when the delivery returns.
  `vmx::wait_registered_for_testing` is a new hidden test seam that reports
  any recorded wait.
- The thread that owns a `MessageHub` batch now waits for another thread's
  open borrowed scope before its nested `batch` closure runs (#1223,
  ADR-0172). The wait records an edge to the borrower, as the owner's `send`
  and `dispose` already did. Before this fix, the nested closure ran inside
  the other thread's borrowed scope. When the wait would close a cycle, the
  nested `batch` enters a borrowed scope (spec/03 §4.1 and §4.2 rule 3).
- `MessageHub` `send`, `batch` and `dispose` no longer wait for a hub owner
  once the hub is disposed or its disposal is requested (#1224, spec/03
  §3.3). A woken waiter stops waiting at the disposal. Before this fix, these
  calls waited for another thread's batch, drain or borrowed scope, and then
  did nothing. A `batch` on such a hub runs its closure and returns its
  value, but it no longer claims the batch owner. So a later call does not
  wait for that closure. A second `dispose` returns at once. C#, Python and
  Swift already behaved this way.
- The inline dispose cascade follows ADR-0175 (spec/02 §7.2, `LIFE-021`,
  #1174, #1167). Once `dispose()` closes hook admission and starts disposing
  children or members, `construct()`, `destruct()` and `reconstruct()` return
  `VmxError::Disposed` before the idempotent no-op and the legality check.
  So `construct()` from `Constructed` and `reconstruct()` from `Destructed`
  now fail too. The background form refuses in the same way, and a queued
  background hook does not run. A transition whose hook returned before the
  cascade started commits nothing more: no settled status, no rollback, no
  queued foreground commit, no deferred child-walk completion, and no
  construct phase of `reconstruct()`. The call returns the hook's own result;
  a container or leaf `reconstruct()` whose destruct phase ended before the
  cascade started returns `Ok(())`. The settled commit and its publication
  now run under one guard, so a cascade that starts in between drops both.
  `status()` can still read the transient or prior status until the cascade
  publishes `Disposed`. Because the settled status now commits inside that
  guard, it changes only after another thread's hub batch or drain ends: a
  `construct()` from inside that batch or drain returns
  `VmxError::ConcurrentOperation` instead of the idempotent `Ok(())`, and a
  subscriber that holds the hub while it waits for the status to settle
  waits forever.
- A leaf `ComponentVm` with `own_member` members disposes them at the same
  admitted-hook boundary as a container's children (#1164, LIFE-015). A
  `dispose()` from another thread while the leaf's construct or destruct hook
  runs publishes `Disposed` first and disposes the members after the hook
  returns. With no hook running on another thread, the members are still
  disposed before `Disposed`. A leaf without members disposes as before. The
  background construct and destruct paths and `reconstruct()` check closed
  hook admission, as `transition_with_body` already did.
- `walk`, `walk_expanded` and `find` no longer panic when they reach a
  `HierarchicalVm` whose lazy children factory returns invalid output (#1060,
  ADR-0170, spec/13 §6.1). `walk` and `walk_expanded` now return
  `VmxResult<Vec<T>>` and `find` returns `VmxResult<Option<T>>`, with the
  `try_children` error. They read children through the new provided method
  `TreeNode::try_children_nodes`, which defaults to `Ok(children_nodes())`.
  The node keeps no children cache, and a later walk retries the factory.
  `children` and `is_leaf` still panic on such output.
- `TokenPagedComposition`: a load that finds a terminal token when it starts now
  fetches nothing (#1161, ADR-0169). A refresh or another load could commit a
  terminal token after the load command admitted the run. The load then
  refetched page 1 and appended it again, and `has_more()` stayed true. The load
  now changes nothing and does not supersede an in-flight refresh. The ad hoc
  `load_more(loader)` call is unchanged.
- `TokenPagedComposition` no longer deadlocks when a `Token::clone` waits for
  another load or refresh of the same pager (#1162). `current_token()` and
  each load cloned the stored token under the cursor lock. Every commit takes
  that lock, and since #1045 it holds the operation gate while it waits. So a
  clone that waited for a refresh to finish, or for a start while another
  commit waited, blocked forever. The pager now stores the token behind its
  own lock, which no commit takes. A reader takes the cursor lock only to copy
  that handle, and runs `Token::clone` after it releases the lock. #1278
  later removed the token lock in this release.
- The `CompositeVm` construct walk's `Current(selector)` assignment follows
  ADR-0165 (#1151). It skips a child that an add, insert, replacement or
  population has attached but not admitted, skips while disposal is pending,
  and skips on the thread whose own transaction of the composite has not
  committed. A disposal from its `on_current_changed` or current-flag
  callbacks returns at once and runs after the publication and any open
  membership transaction end, so the callback reads `Constructing` and a
  foreign add is refused meanwhile. A transfer commit clears `current` only
  while the moved child is still current, so it no longer clears a later
  selection and leaves its flag set.
- The `CompositeVm::destruct` clear holds the publication lease (#1144, Rust
  part). A disposal from `on_current_changed(None)` during destruct is
  deferred until the clear's publication ends instead of running inside the
  callback. The clear still runs while another thread holds a transaction,
  inside the composite's own transaction and while disposal is deferred.
- `FormVm` applies ADR-0174 rule 7 like the other threaded flavors, with
  the wait-for graph of ADR-0176 (spec/20 §5.5, #1160, #1170). Before,
  another thread's `approve()`, `set_model` and `revert()` ran during an
  approval's publication. Its `set_model` was queued, and its settlement
  replayed this thread's queued edits early. Now a `set_model`, `revert()`,
  approval admission, settlement or `dispose()` waits while another thread
  holds a publication scope on the form. An update holds one over its
  `errors_changed` send. A successful settlement holds one until its approval
  subscribers return. A failed settlement holds one over its eligibility
  change. An edit made in the caller's own pre-publication window also
  waits, and only then joins the caller's queue. Disposal ends every such
  wait. Each wait records an edge in the process-wide wait-for graph. A
  wait that would close a cycle does not wait. An example is a hub drainer
  that calls the form while the publisher sends on that hub. A refused
  `set_model` or `revert()` prepares, joins the publisher's queue and returns
  before it takes effect. A refused approval is admitted, and a refused
  settlement commits in its own scope. A refused `dispose()` marks the form
  disposed and returns. The last thread to end its publications tears the
  form down, and a panic in that teardown takes the replay failure route. Each
  thread keeps its own queue and replays it when its outermost publication
  ends. A `dispose()` from another thread now waits for the approval
  subscribers, so they all run. The test
  `another_threads_approval_replays_its_own_deferred_edit` is now
  `another_threads_approval_waits_and_replays_only_its_own_deferred_edit`.
  `disposal_during_an_emission_skips_the_callbacks_not_yet_invoked` now
  disposes from an approval subscriber on the approving thread.
- `FormVm::dispose` no longer completes the channels while another thread
  delivers a form notification outside a publication scope (spec/20 §5.5,
  ADR-0176, #1228). Such deliveries are an approval's admission eligibility
  change, an update's notifications after its `errors_changed` send, and the
  approve command's `approve_errors` send. Before, `dispose()` tore the form
  down at once. Now it marks the form disposed and returns. The delivering
  thread completes the hubs and disposes the commands when the delivery
  returns, as in C# and Python. A `dispose()` from that delivery's own
  observer defers in the same way.
- A validator registration on a live `FormVm` now revalidates as an update
  (spec/20 §5.5, ADR-0176, #1231). `with_validator`, `with_field_validator`,
  `with_model_validator` and `with_clearing_model_validator` revalidated at
  once, without waiting for another thread's publication scope. Their
  `errors_changed` send opened no scope. Now the revalidation waits like
  `set_model`, records its wait in the wait-for graph and sends in an update
  scope. When the wait would close a cycle, the revalidation joins the
  publisher's queue and replays there. The validator itself is registered at
  once.
- A `FormVm` approval started from another approval's settlement notification
  now runs its approval subscribers with model edits applied at once (#1160).
  Before, the outer approval's pre-publication window stayed active, so those
  subscribers' edits were deferred until the outer approval ended. Each
  settlement now saves the enclosing pre-publication state, clears it before
  its subscribers run and restores it when it ends, as C# and Python do. Edits
  made by the outer notification still wait for the outer subscribers.
- `FormVm` now queues every update made during an approval's
  pre-publication window (spec 3.30.0, ADR-0174, `FORM-039`, `FORM-040`)
  (#1168, #1050). The window opens when the post-persist commit starts. A
  `set_model` or `revert` (deny) from `reset_on_approved`, the snapshotter, a
  validator, or a settlement `errors_changed` or eligibility-change observer is
  queued and replays after the approval subscribers return. Before, a call
  from `reset_on_approved` committed at once and the reset overwrote it, and a
  deny from a settlement observer committed at once, so approval subscribers
  saw a reverted model. A queued call now prepares when it is called: a
  validator, `PartialEq` or snapshotter panic reaches the caller and queues
  nothing, and a model equal to the live one is still queued. Before, the
  call queued without preparing, so its panic surfaced only at replay, failed
  the settled approval and dropped the later queued updates. Each update now
  replays under its own unwind guard. After the last replay, the first replay
  panic resumes from `approve()`, unless a failed commit or a panicking
  approval subscriber wins. When the post-persist commit fails, the updates it
  queued replay after the failed settlement's eligibility change and before
  the failure is returned. Call-time preparation runs the validators once more
  for each queued update. Calls from other threads now wait for the
  publication instead of joining the queue (see the ADR-0176 entry).
- `CompositeVm`, `GroupVm` and `AggregateVm1`…`AggregateVm6` no longer dispose
  their children while their admitted construct or destruct hook runs on another
  thread (#1062, LIFE-015). The child cascade now runs at the hook boundary of
  the container's own disposal. A foreign `dispose()` publishes `Disposed`,
  waits for the hook, and then disposes the children. On a wait-for cycle, the
  hook's thread disposes them when the hook returns. That thread's `construct()`
  or `destruct()` then returns the first child failure, unless the call failed
  already. With no foreign hook, the children are still disposed before the
  container publishes `Disposed` (LIFE-013). A `construct()` or `destruct()` of
  the container during that cascade returns `VmxError::Disposed` and publishes
  nothing. A child walk of a disposed container starts no further child and does
  not run its selector. A `ComponentVm` child walk also stops: once the
  component is disposed, `ChildTransitions::transition` starts no member, `then`
  does not run, and both return `Ok(())`. A second `dispose()` of a
  `CompositeVm` or `GroupVm` returns `Ok(())` at once. So a child that disposes
  its parent no longer makes the parent publish `Disposed` before the remaining
  children.
- `TokenPagedComposition` no longer commits a refresh or load that a later load
  superseded (#1045). An operation started with no lock, so a load could start
  between a commit's last staleness check and its writes. The load then
  appended a page fetched for the old prefix to the new accumulator. A start
  now takes an operation gate. Each commit holds that gate from its final check
  until it has written the items and the cursor.
- `FormVm::is_dirty` on another thread no longer pairs a model and a
  snapshot that never coexisted (#1073). A reset approval replaces both in two
  steps, so a clean reset could read as dirty. An approval that advanced the
  snapshot after an edit could also read as clean. `is_dirty` now reads the
  pair again when an approval commit overlapped its reads. It still holds no
  lock while `PartialEq` runs.
- A `FormVm` approval with `reset_on_approved` now validates the reset model
  under the update lock, before it commits (#1046). Before, a validator
  registered on another thread during that validation was left out. The
  approval then committed stale errors, so an invalid reset model read as
  valid. A validator registered meanwhile now revalidates the committed model.
  A re-entrant registration during the validation makes it run again, until a
  run registers no validator.
- A `FormVm` approval started from an approval subscriber no longer applies
  the outer approval's deferred edits early (#1061). Before, the outer
  approval's later subscribers saw the edited, dirty model instead of the
  settled one. Only a thread's outermost settlement now applies the deferred
  edits, after its own subscribers have run, as C# does for nesting on one
  thread. An edit that a subscriber of the outermost approval makes still
  applies at once.
- `ServicedObservableCollection` and `KeyedServicedObservableCollection` no
  longer deliver a stale message after user code panics under a mutation
  (#1065). User code runs under a mutation: `PartialEq` in `remove`, and the
  `Drop` of an item or key that the mutation removes, replaces or clears. When
  that code mutated the collection and then panicked, the nested change stayed
  queued. The next mutation delivered it before its own change. The queued
  messages are now discarded, as they already were when a subscriber panics.
- `CompositeVm::add`, `CompositeVm::insert`, `GroupVm::add` and `GroupVm::insert`
  no longer deadlock when admission fails and a subscriber disposes the
  container (#1066). The rollback destructed the child while it held the
  membership gate. A subscriber that disposed the container from the child's
  destruct messages then waited for that gate on the same thread. The rollback
  now releases the gate first, as `replace` already did. The call returns
  `VmxError::Disposed`, and the container ends `Disposed`.
- A cross-thread `dispose()` of a `CompositeVm`, `GroupVm` or fixed aggregate
  no longer hangs when its wait would close a wait-for cycle (ADR-0153,
  ADR-0167, #1058). Before, two threads that each held one container's
  membership transaction and disposed the other's container waited for each
  other forever. Transaction owners and disposal waits are now recorded in one
  process-wide wait-for graph. The disposal that would close a cycle records
  the intent and returns, and the transaction owner disposes the container
  when its transaction ends. If that owner's `add` has not admitted its child
  yet, the `add` returns `VmxError::Disposed` and rolls the child back. A
  disposal that closes no cycle still waits for the transaction.
- The summary line of `ModalVm::open()` now says that the call has no effect
  and does not reopen a dismissed modal. Before, it said that the call marks
  the modal as open (#799).
- Rustdoc now matches current behavior (#790). The `ValueStream` type doc says
  that `ValueStream::new` replays the current value and `ValueStream::hot` does
  not, with a doctest. `AsyncRelayCommand::execute` (inherent and trait) points
  to `error_stream()` for failures. The `FormVm` type doc states that a
  validator registration after `dispose` has no effect. The `background_errors()`
  docs on the composites, the group and the aggregates describe the deferred
  failures the stream carries, not only those that settle after the call
  returns. The parity ledger limits "no join of an in-flight child" to
  `AggregateVm1`–`AggregateVm6`.
- A `FormVm` reader on another thread no longer pairs one model with another
  model's errors. Before, `set_model` and `revert` installed the model before
  its errors. An approval reset installed the errors before the model. So
  `is_valid()` could report the wrong validity. Now, once a reader sees the new
  model, `is_valid()`, `can_approve()`, `errors()`, `error_map()`, and
  `field_error()` report that model's errors, or a later model's. Readers still
  hold no lock while `PartialEq` or a validator runs (#770).
- `MessageHub` delivery no longer locks the hub before each subscriber to
  check that it is still attached. Each subscriber now carries an active
  flag. Unsubscribing, dropping the `Subscription` and disposing the hub clear
  the flag under the hub lock, and delivery reads it before each handler. A
  subscriber detached by an earlier handler of the same message is still
  skipped, and a handler that detaches itself still finishes its message.
  Delivery also marks the hub as delivering once per message instead of once
  per handler. A detached handler still drops right after its own turn,
  outside that mark, so its `Drop` sees the same state as before. A release `send` to 100 subscribers drops from about 1,650 ns
  to about 570 ns. Before #636 it cost about 540 ns (#766).
- `ObservableDictionary` and `ObservableMultiDictionary` lookups, and
  `remove(&item)` on `ServicedObservableCollection` and
  `KeyedServicedObservableCollection`, no longer copy every stored key or
  item on each call. They compare against a shared copy-on-write snapshot,
  still with no VMx mutex held, and a write copies only while a snapshot is
  in use. A release `get` over 5,000 `String` keys drops from about 87,000 ns
  to about 4,700 ns, the cost before #636. Inserting a key that is already
  present now drops the argument key after the lock is released (#765).
- The documentation of `HierarchicalVm::construct` and
  `HierarchicalVmBuilder::eager_children` no longer claims all descendants. The
  option applies to this node's children only. It continues deeper only
  through children that are eager themselves (#759, ADR-0156).
- `DiscriminatorVm::active_key_changes()` ends on the active key when a
  newer setter commits between a setter's commit and its publication: on
  another thread, or from the replaced key's `Drop`. The older setter's key
  is then skipped on the stream; `active_changed()` still sends one message
  per effective change (#752).
- `DerivedProperty::recompute` no longer loses an update that commits while
  its transform runs. Concurrent `recompute` calls now run one at a time, so
  each transform receives the previous result. A source update that commits
  during a transform wins over the transform's stale result. No lock is held
  while subscribers run, and the last value that `value_changes` publishes is
  the stored value. A commit no longer lands after `dispose()` returns (#751).
- A `CompositeVm`, `GroupVm`, or fixed-slot aggregate that waits for a
  background child no longer leaks when its last handle drops without
  `dispose()` and the child never settles. Queued child steps, the settle
  callback on the awaited child, the start-record waiter, the composite's
  selector step, and the deferred construct of `reconstruct()` and the
  reconstruct command now hold the container weakly. The container, not the
  callback, keeps the awaited child. Before, these references formed cycles,
  so the container and its children were never freed. A container that
  nothing references any more (no handle and no command) abandons its
  transition; the child still settles. A command handle alone still lets
  an aggregate's deferred reconstruct complete (#750).
- `CompositeVm::clear()` publishes the current child's `is_current` change
  after it releases the membership gate. Before, a hub or `property_changed()`
  subscriber that disposed the composite from that notification blocked on
  the gate its own thread held, and `clear()` never returned (#749).
- The blanket `Reconstructable::reconstruct` now waits for a deferred
  destruct and then constructs again, as the inherent `reconstruct` does.
  Before, it called `construct` while the destruct was still in flight,
  ignored the `ConcurrentOperation` error, and left a background component,
  or a container or aggregate with a background child, `Destructed` (#748).
- `ServicedObservableCollection::remove` and
  `KeyedServicedObservableCollection::remove` that find no match deliver a
  change their `PartialEq` made to the collection before they return. Before,
  that change waited in the delivery queue until a later mutation drained it,
  or was never delivered (#747).
- `ManualDispatcher::drain_foreground` and `drain_background` release the
  queue lock before each action runs, as `drain()` does. Before, an action
  that dispatched to the same queue, such as a background hook that
  constructs another background VM, blocked on that lock and the drain never
  returned (#746).
- `CompositeVm` and `GroupVm` with `auto_construct_on_add` no longer
  publish `Constructed` while a child added after the construct walk's last
  late scan is still `Constructing` (#744, spec/02 §6, spec/06 §5.1). Before,
  an add that read `Constructing` after that scan started its child with no
  record the walk would wait on. The walk's record scope now stays open
  until it seals: after the selector runs (once), the walk scans again under
  the membership gate and joins any child an add started meanwhile. With none
  left, it flips the container to `Constructed` in that same gated section,
  so a later add follows the add-after-`Constructed` rule, and the container
  publishes `Constructed` once, as before. Until that publication starts,
  `status()` reads `Constructed` but the transition is still in flight:
  `can_construct()`, `can_destruct()`, `can_reconstruct()` and the
  reconstruct command report `false`, and `construct()` and `destruct()`
  return `ConcurrentOperation`, as during `Constructing`.
- The construct walk of `CompositeVm` and `GroupVm` no longer rolls the
  container back when it reaches a child that a cross-thread add attached
  during `Constructing` but has not started yet (#743, spec/06 §5.1). Before,
  the walk found that child `Destructed` and failed. Now an add that will
  auto-start its child registers a start record as it attaches the child, and
  marks it done right after its construct attempt, before it publishes the
  collection change. The walk never starts a late child: it waits for that
  attempt and then joins the child. A late child without a record (for
  example, one added while `auto_construct_on_add` was off) is skipped. The
  walk no longer reads the flag at all, so `set_auto_construct_on_add(false)`
  during the walk no longer makes it fail on a child added later. A late child
  whose construct fails still rolls the container back, and its add fails
  and is undone. The walk scans for late children under the membership gate,
  so it never sees a child whose add has not registered its record yet. Each
  walk keeps its records in its own scope, which ends with that walk, so a
  failed or superseded walk never takes or clears a later walk's records, and
  an add after the walk's last scan keeps no record.
- `FormVm` replays a model edit deferred during an approval settlement even
  when an approval subscriber panics, then lets the panic continue to the
  `approve()` caller, as the other flavors do in `finally`. Before, the edit
  was skipped and the next successful approval replayed it over newer edits
  (#740).
- `RelayCommand`s built from clones of one `RelayCommandBuilder` share their
  action, but a nested call deferred between them now uses its own command's
  disposal state. Before, a deferred call ran after
  its own command was disposed, or was dropped when the outer command was
  disposed (#739).
- A component whose lifecycle hook panics now releases its settle waiters as
  the panic unwinds. Before, a `CompositeVm` or `GroupVm` waiting on a
  background child whose `on_dispose` hook panicked stayed `Constructing`,
  and its later `construct()` and `destruct()` returned
  `ConcurrentOperation`. `transition_with` and `reconstruct` release the
  waiters through a drop guard; the panic still reaches the caller (#738).
- A container no longer deadlocks when a background child settles and a
  queued child step owns the last handle to a view-model. Settling, starting a
  transition and rolling one back now drop the cleared settle queue after the
  hub and container locks are released. Before, dropping the composite while a
  failing background child settled, or removing a queued child and dropping
  its handle, blocked the hub (#701).
- `GroupVm::construct`, `reconstruct()` and the reconstruct command no longer
  deadlock when a child hook or hub subscriber adds a child or calls
  `set_auto_construct_on_add` during the construct walk. The group reads its
  auto-construct flag before the walk, as `CompositeVm` does. Before, the walk
  held the flag's lock, so the re-entrant call waited forever (#702).
- Disposing a `CompositeVm`, `GroupVm` or aggregate while it waits on a
  background child no longer deadlocks when a queued child step owns the last
  handle to a removed child whose model `Drop` reads the container. The
  abandoned settle queue now drops after the container's core lock is
  released (#741).
- `CompositeVm` no longer deadlocks when its current selector, its
  `on_current_changed` callback or a hub subscriber to `current` re-enters the
  composite. The selector and callback are cloned out before they run. A
  callback fired by `construct()`, `reconstruct()`, the reconstruct command or
  `destruct()` can now change the selector or the current child, and any
  callback can replace itself. A callback fired by `set_current` still gets
  `OwnershipTransactionInProgress` if it changes the current child
  (spec/06 §3.2). Before, each call ran under the mutex that stores it (#716).
- `FormVm::approve` no longer persists an invalid model while another thread
  calls `set_model`. Admission now checks validity, marks the approval in
  flight and captures the model under the form's update lock, which
  `set_model` also takes. Before, an edit could commit between the check and
  the capture, so the persister, the snapshotter and `on_approved` received a
  model the validators reject (#719).
- A `TokenPagedComposition` built with `with_auto_construct_loader` no longer
  commits a load or refresh that an item's construct hook superseded. The
  load and refresh tasks now check the operation generation and disposal
  before each item's construct and again before the commit. A stale operation
  constructs no further items, commits nothing and publishes nothing
  (spec/21 §6.2), and a construct hook that disposes the pager also stops the
  loop. Items it already constructed are dropped without a destruct, as in
  the other flavors. Before, the tasks checked the generation only before the
  construct loop (#720).

## [0.35.0] — unreleased source version

### Added

- `CompositeVm`, `GroupVm`, `ModeledCompositeVm`, and `AggregateVm1` to
  `AggregateVm6` expose `background_errors()`, like `ComponentVm`. The stream
  reports a background child failure that rolls the container back
  (spec/11 §2, ADR-0130).
- `VmNode::when_lifecycle_settled` and `LifecycleSettleCallback` are
  documented. A user `VmNode` wrapper can forward the hook so its container
  waits for a background child. A wrapper that does not forward it still works:
  the container accepts the child while it is in flight, as before.
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
  flavor), and `entries()`, an insertion-ordered snapshot (spec/21 §4).
  COL-010..012, COL-014, COL-015, and COL-022 now exercise the two-key
  dictionary instead of the single-key one.
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

- A background child that fails before its `CompositeVm`, `GroupVm`, or
  `AggregateVm1`–`AggregateVm6` container's own construct or destruct action
  returns no longer leaves the container at its target status. The container
  previously published the rollback status and then its target status (for
  example `Constructing`, `Destructed`, `Constructed`). It now records the
  failure, skips the remaining child steps, and publishes one rollback status
  when the action returns. The failure goes to `background_errors()`, the same
  as a child that fails after the action returns.
- With `auto_construct_on_add(true)`, a child added to a `CompositeVm` or
  `GroupVm` while it is Constructing is no longer left Destructed while the
  container reaches Constructed (spec/02 §6). The add now constructs a
  Destructed child at once and leaves a Constructing or Constructed child
  alone. The construct walk, including the one `reconstruct` runs, joins
  without restarting it a member that is already Constructing, for example one
  added by the container's construct hook. It also joins each member added
  during the walk. The container stays Constructing until that child settles.
  If a child added during the walk fails, the container rolls back once and
  reports the failure. A child added after the walk ends is constructed but
  not awaited. Nothing changes with auto-construct off.
- Disposing a `MessageHub` subscription, dropping it, or disposing the hub no
  longer deadlocks when a subscriber's handler owns the last reference to
  another subscription on the same hub. Removed handlers, completions, and
  queued messages are now dropped after the hub's lock is released. The same
  applies to `ValueStream` subscriptions and disposal, and to the
  `property_changed()` stream.
- A user value or closure whose `Drop` reads or mutates its owner no longer
  deadlocks when VMx replaces, discards, or clears it. Replaced form field
  validators and disposed form validators, invalidated hierarchical children
  and parked batch items, replaced composite selectors, current-changed
  callbacks, filtered predicates and filtered current items, cleared composite
  and group children, removed `AggregateChangeStream` entries, replaced
  `PagedComposition` sources, replaced `ValueStream` and `DerivedProperty`
  values, and replaced `AsyncResourceVm` states are now dropped after the
  owning lock is released.
- A hub subscriber disposed by an earlier subscriber while a message is being
  delivered no longer receives that message, as in C#, Python, and
  TypeScript. A subscriber that disposes itself still finishes the message it
  is handling.
- Every published lifecycle status change (construct, destruct, reconstruct,
  dispose, and rollbacks) now raises the local `status` and then
  `is_constructed` notifications on `property_changed()` after the hub
  `ConstructionStatusChanged`, as the other flavors do (spec/01 §1, spec/02
  §6). They are local only; no hub `PropertyChanged` is sent for them.
  Before, Rust raised neither.
- `AggregateVm1` to `AggregateVm6` `reconstruct_command()` runs
  `reconstruct()`, so slot factories re-run and replaced children are
  disposed (spec/05 §5, spec/08 §4). Before, the command destructed and
  constructed the current slots in place.
- Fixed aggregates reject a factory candidate that is the aggregate itself or
  one of its ancestors with `VmxError::OwnershipCycle` before any slot commits
  (spec/08 §2, §4). Before, the aggregate became its own slot and parent,
  failed with `ConcurrentOperation`, and every later construct failed with
  `InconsistentParent`.
- `ObservableDictionary` and `ObservableMultiDictionary` hub `Add` messages
  carry the insertion index in `new_index`, as the other flavors do
  (spec/21 §2.4). Before, every action sent `None`.
- `DerivedProperty::set_value` reports a disposed property and a rejected value
  with separate messages. Before, both said "derived property is read-only".
- `FormVm::dispose` no longer publishes `ConstructionStatusChanged`
  (`Disposed`) on the form's hub. The hub carries only the spec/20 §8
  messages, the model `PropertyChanged` and `FormReverted`, as in the other
  flavors.

- `Reconstructable::reconstruct` does nothing outside Constructed, as the
  lifecycle rule and `can_reconstruct()` say. Before, it constructed a
  Destructed node (spec/14 §2.3).
- `reconstruct()` on a component, composite, group, or aggregate returns
  `ConcurrentOperation` during another transition and `Disposed` after
  disposal, as the lifecycle core does (spec/02 §2.1, LIFE-008). Before, these
  wrappers returned `InvalidLifecycleTransition` for both.
- `CompositeVm`, `GroupVm`, `ModeledCompositeVm`, and `AggregateVm1` to
  `AggregateVm6` stay Constructing or Destructing until every background child
  settles. Then they publish their own terminal status (spec/02 §6). Children
  still transition in order. The composite's current selector runs after the
  last child. A child that settles at any other status rolls the container
  back (LIFE-014). Disposing a container while it waits publishes no rollback
  and no terminal status. `reconstruct` constructs after a deferred destruct
  settles. All-synchronous emission order does not change. A synchronous child
  that returns `Ok` but is not at the target status now fails the container,
  as in C# and TypeScript (for example, an observer that destructs the child
  from its Constructed message).
- User `PartialEq` code no longer runs while a VMx mutex is held, so an `eq`
  that reads its owner returns instead of deadlocking. These operations now
  compare copies outside the lock: `ComponentVm::set_model`, serviced and keyed
  collection `remove`, `ObservableDictionary` and `ObservableMultiDictionary`
  key lookups, `DiscriminatorVm` key changes and `is_active`, and
  `TokenPagedComposition` refresh. Each commit checks a generation or revision
  and searches again if the state changed. Replaced and removed values are
  dropped after the lock is released. Semantics and emission order do not
  change.
- User `Drop` code no longer runs while a VMx mutex is held, so a value whose
  `drop` reads its owner returns instead of deadlocking.
  `DiscriminatorVm::clear_modals` and `dispose` release saved modal keys, and
  `ServicedObservableCollection::clear` and `replace_all`,
  `KeyedServicedObservableCollection::clear`, `replace_all`, `upsert`,
  `replace`, `remove_at`, and `remove_key`, and `ObservableList::clear` and
  `replace_all` release old items and captured keys, only after the lock is
  released. Emission order is unchanged.
- `NotificationVm::advance_by_ms` and `ConfirmationVm::advance_by_ms`
  saturate the elapsed clock. A large advance used to overflow: a panic in
  debug builds, and in release builds a wrapped clock that left the
  notification undismissed.
- `HierarchicalVm::try_children` returns an error when the children factory
  re-enters materialization on its receiver (for example through `is_leaf`),
  instead of panicking.
- Documented the panics of `HierarchicalVm::children`, `is_leaf`, `is_first`,
  `is_last`, and `TreeNode::children_nodes` (the fail-fast accessor of spec/18
  §4 and ADR-0127; `try_children` is the fallible one), and of
  `DerivedProperty::from_sources` and `from_sources_with_write_back` on an
  empty source list.
- `SearchableState::search` announces the projection on `filtered_changed`, as
  the pushed filtered output of the other flavors does, including after the
  source signal is disposed (SRCH-005).
- `DecoratorCommand` runs its post-action once when the inner command panics,
  then continues the panic (CMDD-013, spec/04 §8.4).
- `FormVm::with_validator` keys each registration's errors separately, so a
  second whole-model validator no longer replaces the first one's errors, and
  a registration after dispose is inactive (spec/20 §10).
- `HierarchicalVmBuilder` defaults an unset hint to `Some("")`, like the other
  builders (spec/10).
- Rustdoc for `AsyncRelayCommand::with_can_execute` (it replaces the predicate)
  and for `ValueStream` subscriptions on a hot stream (no replay) now matches
  the behavior.
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
  now does, see below). An async selection queued before `dispose()` does
  not run afterwards.
- `FormVm` validators registered after `dispose()` are inactive, as the type
  documentation states; before, they revalidated the disposed form.
- A disposed view model ignores `expand`, `collapse`, and
  `toggle_expansion` (disposal contract).
- An approval subscription disposed by an earlier subscriber during the same
  emission releases its captured state at once, not at the end of the
  emission (ADR-0139).
- A post to a disposed `NotificationHub` returns a pending result without
  replacing a stored terminal reaction (DISP-004).
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
