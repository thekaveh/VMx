# 6.8. Disposal Contract

VMx disposal is safe to call from independent teardown paths. If a public
VMx-owned type exposes `Dispose()` / `dispose()`, the first call claims its
terminal work and every later or re-entrant call is a no-op. Completion,
terminal notifications, cancellation, and owned-resource cleanup happen at
most once.

This rule removes the need for host-side “already disposed” flags. It does not
make all later API calls behave alike: each type keeps its documented
post-dispose behavior.

## 6.8.1. Modeled Assignment After Disposal

Modeled assignment has one portable terminal rule in all five flavors. An
assignment that starts after disposal returns immediately. It does not compare
the candidate for equality. It does not change the retained model or the
snapshot. It does no modeled-hint work, validation, or command-state
recomputation. It calls no consumer callbacks. It sends no local notifications
and no hub messages. The last accepted model and all derived state values stay
readable and unchanged.

This admission guard covers modeled components and `FormVM`. Modeled
composites do not expose a settable retained model—their model input
configures a child factory—so they need no separate guard.

An assignment admitted before disposal keeps its ordinary completion and
notification contract. Continue cancelling network requests, renderer work,
tasks, and other application operations when their resources are no longer
needed; the VM guard prevents late state admission but does not replace
resource cancellation.

## 6.8.2. The Seven Disposal Families

| Family                        | Representative surfaces                                             | Cross-cutting ID | Detailed coverage                                         |
| ----------------------------- | ------------------------------------------------------------------- | ---------------- | --------------------------------------------------------- |
| VM and owner cascades         | Component, composite, group, aggregate, hierarchy, forwarding       | `DISP-001`       | `LIFE-004`, `LIFE-012`, `LIFE-013`, `LIFE-018`, `CVM-009` |
| Commands                      | Relay, async relay, composite/decorator, modeled CRUD               | `DISP-002`       | `CMD-012`, `CMD-013`, `CMDD-010`..`CMDD-013`              |
| Hubs and services             | Message hub, notification hub                                       | `DISP-003`       | `HUB-012`, `NOTIF-017`                                    |
| Interaction owners            | Form, modal, notification rendering VMs                             | `DISP-004`       | `DIA-011`, `DIA-012`, `FORM-014`, `NOTIF-017`             |
| Reactive helpers              | Derived property, expansion/search state, discriminator             | `DISP-005`       | `DPROP-011`                                               |
| Collection/projection helpers | Batch handles, paging, filtered projections, disposable collections | `DISP-006`       | `COMP-013`, `COMP-035`, `GRP-006`, `COL-024..031`         |
| Async resource owners         | AsyncResourceVM loader, commands, and accepted value                | `ARES-010..011`  | `ARES-005`, `ARES-008`, `ARES-009`                        |

`AggregateChangeStream` disposal is covered by `AGCH-010`.

Only types that are documented as thread-safe support disposal that races other
calls. These types claim terminal work atomically. Single-threaded flavors and
helpers still support repeated and re-entrant disposal on their execution
model.

## 6.8.3. Ownership Rules

- Every VM exposes its injected message hub as a read-only baseline member. The
  hub is shared infrastructure: VM disposal never disposes it.
- Subclass-owned, disposal-lifetime resources can be registered through
  `Own` (C#), `_own` (Python), or `own` (TypeScript, Swift, Rust). Cleanup runs
  exactly once in LIFO order after the subclass disposal hook. One failing
  cleanup is swallowed without blocking the rest.
- Registration after disposal cleans the resource immediately once.
- Reconstruct and destruct do not release disposal-lifetime registrations.
  Per-construct resources remain explicit in `OnConstruct`/`OnDestruct`.
- Container VMs (composites, groups, aggregates) dispose their children
  depth-first before their own teardown (`LIFE-013`). The order is children,
  the container's `Disposed` publication, subclass hook, LIFO owned
  registrations, stream completion, then commands. A child reached through
  several teardown paths has one observable terminal transition.
- A child view-model registered with the owned-resource helper is not a
  container child. It is disposed parent-first: the parent publishes
  `Disposed`, runs its subclass hook, and then disposes owned registrations,
  including that child, in LIFO order.
- A member view-model registered with the member-disposal helper (`OwnMember`
  in C#, `_own_member` in Python, `ownMember` in TypeScript and Swift,
  `own_member` in Rust) is disposed depth-first instead: members are disposed
  in registration order before the parent publishes `Disposed`, after a
  container's own children (`LIFE-018`, spec 02 §7.1).
- A terminal cascade does not stop at a failing child or subclass hook. The
  teardown of every sibling still runs. The base teardown of the parent also
  runs. Flavors that throw or return results report the first failure only
  after all mandatory cleanup completes.
- Disposal deferred by an ownership transfer runs after commit or rollback.
- A committed transfer publishes both membership events before it propagates a
  disposal failure.
- If rollback also triggers failing disposal, an earlier attachment failure
  stays first.
- Disposal requested from a current-changed callback is likewise deferred until
  selection publication finishes, without blocking the callback on its own
  membership transaction.
- Disposal that races an admitted construct or destruct hook waits until the
  hook settles. Terminal resource and stream teardown follow.
- Opposing hooks that cross-dispose use cycle-aware deferral. Neither thread
  deadlocks, and no post-hook child work begins after the parent becomes
  terminal.
- A forwarding VM delegates disposal to the wrapped VM; it does not introduce
  reference counting. Resources registered through a forwarding VM belong to
  the wrapped VM and are released with its other registrations (`FWD-005`).
- Command decorators and composites do not dispose caller-owned inner commands
  unless their type-specific contract explicitly says they own them.
- `ServicedObservableCollection` and `KeyedServicedObservableCollection` never
  own or dispose their items and do not implement VM child-collection lifecycle
  interfaces.
- Subscription and batch handles release only the registration or batch scope
  they represent.
- `AsyncResourceVM` cancels active acquisition and releases its last accepted
  value on disposal. A loader that completes late cannot publish or become
  current; its acquired value is cleaned exactly once. Python invalidates the
  resource synchronously and schedules native cancellation and late-result
  registration on the operation loop. A caller-owned loop must stay runnable
  until admitted work is cancelled and drained; see
  [Python asyncio dispatcher ownership](services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership).

## 6.8.4. Portable Inventory

This table lists the public disposal surfaces of VMx view models, commands,
collections, services, and Rust subscription handles. Test-support recorders
are not listed. In every row, a second or re-entrant dispose is a no-op. The
table uses concept names;
[Flavor Exceptions](#685-flavor-exceptions) lists spellings and every
flavor-specific difference.

| Type                                                                           | Dispose behavior                                                      | Later calls                                                                 | Released                                                                                                                                                                                           | Readable state            |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| VM families: component, read-only, composite, group, aggregate 1–6             | One `Disposed` transition; VM-local streams complete                  | Lifecycle calls other than dispose fail; changes are inert                  | Children depth-first, then subclass hook, LIFO owned registrations, stream completion, commands                                                                                                    | Status                    |
| `HierarchicalVM`                                                               | One `Disposed` transition; VM-local streams complete                  | Lifecycle calls other than dispose fail; changes are inert                  | No children, which stay live (see [Disposing A Subtree](viewmodel-families/hierarchical-family.md#6264-disposing-a-subtree)); subclass hook, LIFO owned registrations, stream completion, commands | Status                    |
| Forwarding component and composite VMs                                         | Delegates to the wrapped VM, which completes once                     | Wrapped VM contract                                                         | Delegates to the wrapped VM                                                                                                                                                                        | Wrapped VM contract       |
| Message hub                                                                    | Message stream completes once                                         | Sends are ignored                                                           | Pending transaction queue and subject                                                                                                                                                              | —                         |
| Relay command, with and without parameter                                      | Terminal disabled state                                               | `CanExecute` is false; execute is inert                                     | Trigger subscriptions                                                                                                                                                                              | —                         |
| Async relay command                                                            | Owned error channel completes once; the active operation is cancelled | Disabled; execute is inert                                                  | One active cancellation handle and trigger subscriptions                                                                                                                                           | —                         |
| Composite, decorator, confirmation-decorator, and modeled-CRUD commands        | Owned error channel completes where present                           | `CanExecute` is false; no inner work starts                                 | Event subscriptions and owned relay commands only; caller-owned inner commands stay caller-owned                                                                                                   | —                         |
| `FormVM`                                                                       | Approval, error, and validation streams complete once                 | Approve and deny are inert                                                  | Approve and deny commands                                                                                                                                                                          | Model and snapshot        |
| Notification hub                                                               | Pending stream completes once; waiters resolve `Pending`              | Post resolves `Pending`; resolve is inert                                   | Pending queue and waiters                                                                                                                                                                          | —                         |
| `NotificationVM`, `ConfirmationVM`                                             | Property-change stream completes once                                 | —                                                                           | Timers, pending subscription, commands                                                                                                                                                             | Last render state         |
| `ModalVM`                                                                      | Idempotent dismiss; completion resolves once                          | —                                                                           | Waiters                                                                                                                                                                                            | First result              |
| `DerivedProperty`                                                              | Value-change stream completes once                                    | No recompute emission                                                       | Source subscriptions                                                                                                                                                                               | Last value                |
| `ExpandableState`                                                              | Expansion stream completes once                                       | Mutations and commands are inert                                            | Expansion subscribers; expand, collapse, and toggle commands that were read                                                                                                                        | Last expansion value      |
| `SearchableState`                                                              | Search streams complete once                                          | Setters and search are inert                                                | Search and source subscriptions                                                                                                                                                                    | Search term reads empty   |
| `FilteredCompositeVM`, `ScoredFilteredCompositeVM`                             | Projection stream completes once                                      | The projection stops changing                                               | Source subscription                                                                                                                                                                                | Frozen visible projection |
| `PagedComposition`                                                             | Paging streams complete where exposed                                 | Pages are read without source tracking                                      | Source subscription                                                                                                                                                                                | Page reads                |
| `TokenPagedComposition`                                                        | Command stream completes once                                         | Late fetch results cannot mutate or publish                                 | Load-more and refresh commands                                                                                                                                                                     | Accumulated state         |
| Batch handles from list, composite, and group operations                       | At most one Reset at outer batch exit                                 | The handle has no other behavior                                            | One batch depth claim                                                                                                                                                                              | —                         |
| `AggregateChangeStream`                                                        | Output subscriptions complete once                                    | New subscriptions complete at once; membership and item changes are ignored | Structural subscription and selected item subscriptions; never source items                                                                                                                        | —                         |
| `DiscriminatorVM`                                                              | Active-change stream completes once                                   | Mutations are inert                                                         | Stream subject                                                                                                                                                                                     | Reads                     |
| `AsyncResourceVM`                                                              | Active operation is invalidated; commands and state stream complete   | Late work cannot publish                                                    | Cancellation handle; accepted or late value is cleaned once                                                                                                                                        | Terminal state            |
| `ObservableList`, `ObservableDictionary` (Python only)                         | Every VMx-owned collection subject completes once                     | Mutations emit nothing                                                      | Collection subjects                                                                                                                                                                                | Stored contents           |
| Hub, property-change, approval, and aggregate-change subscriptions (Rust only) | No completion surface                                                 | The handle has no other behavior                                            | One subscriber registration                                                                                                                                                                        | —                         |
| `MessageRecorder` (Rust only)                                                  | Recording stops; the hub detaches the recorder                        | No later message is recorded                                                | Hub registration                                                                                                                                                                                   | Recorded messages         |
| Value streams and their subscriptions (Rust only)                              | Subscribers complete once; subscriptions detach                       | Later sends are inert                                                       | Subscribers                                                                                                                                                                                        | Last value                |

Rows marked "only" exist in the named flavor. Every other row applies to every
flavor unless the exceptions below say otherwise.

## 6.8.5. Flavor Exceptions

### 6.8.5.1. C\#

- `MessageHub`, `AsyncRelayCommand`, and `TokenPagedComposition` claim disposal
  under a gate. `NotificationHub` claims it under a lock.
- VM lifecycle calls other than dispose raise. Selection and property changes
  are inert.
- `RelayCommand` and `RelayCommand<T>` can raise one final `CanExecuteChanged`
  before the terminal disabled state.
- The message stream is `Messages`; the derived-property stream is
  `ValueChanged`. Post-dispose `DerivedProperty<T>` writes follow the
  type-specific validator contract.
- `NotificationVM` and `ConfirmationVM` stop their property-change surface.
  Later resolution paths are inert.
- Filtered projections expose no projection stream; the projection stops
  changing. `PagedComposition<T>` has no completion surface.
- `AsyncResourceVM<T>` releases its cancellation token source and loader
  registration.
- `AggregateChangeStream<T>.Batch` throws `ObjectDisposedException` after
  disposal.

### 6.8.5.2. Python

- VM families claim disposal under the lifecycle lock. `MessageHub` and
  `NotificationHub` use their own locks. `AsyncResourceVM` uses its resource
  gate.
- The terminal status is `DISPOSED`; illegal lifecycle calls raise.
- Commands complete their owned subjects once. The async relay command cancels
  one in-flight task.
- `NotificationHub` futures resolve `PENDING`, and post resolves `PENDING`.
  `ModalVM` resolves its awaiting futures once.
- `PagedComposition` and `TokenPagedComposition` complete paging streams where
  exposed and release source subscriptions and paging commands. Reads remain;
  late token fetches cannot mutate.
- `ObservableList` and `ObservableDictionary` are disposable only in Python.
- `AsyncResourceVM` invalidates the active operation synchronously. Native
  cancellation and late-value cleanup run on the operation loop; see
  [Ownership Rules](#683-ownership-rules).
- `AggregateChangeStream.batch()` raises `RuntimeError` after disposal.

### 6.8.5.3. TypeScript

- The terminal status is `Disposed`; illegal lifecycle calls throw.
- Commands complete their owned subjects once. The async relay command aborts
  one `AbortController`.
- `NotificationHub` promises resolve `Pending`. `NotificationVM` and
  `ConfirmationVM` release scheduler handles. `ModalVM` resolves its promise
  once.
- `PagedComposition` and `TokenPagedComposition` follow the Python paging
  behavior above.
- `BatchUpdateHandle` also implements `[Symbol.dispose]`.
- `AsyncResourceVM<T>` releases an abort controller.
- `AggregateChangeStream.withBatch` throws `Error` after disposal.

### 6.8.5.4. Swift

- `ObservableList` and `ObservableDictionary` expose no VMx disposal member and
  are outside this inventory.
- Publishers finish rather than complete. The terminal status is `.disposed`;
  illegal lifecycle calls throw.
- VM families claim disposal under the lifecycle lock. `MessageHub` and
  `NotificationHub` use their own locks. `TokenPagedComposition` claims it on
  its state queue.
- `MessageHub` releases only its pending transaction queue.
- Commands release cancellables and one active task.
- `NotificationHub` continuations resume `.pending`, and post returns
  `.pending`. `NotificationVM` and `ConfirmationVM` release a timer, tick,
  pending subscription, and commands.
- The modal type is `BasicModalVM`; its continuations resume once.
- `PagedComposition` finishes its property-change publisher once and releases
  the source-composite cancellable. Reads and direct paging remain available.
- `TokenPagedComposition` finishes its collection, property, and command
  publishers once.
- `BatchUpdateHandle` uses `deinit` as a safety net.
- `AsyncResourceVM<T>` cancels its operation task.
- `AggregateChangeStream.withBatch` after disposal runs the body and emits no
  `Batch` event.

### 6.8.5.5. Rust

- `PagedComposition`, rendering `NotificationVm`, `ConfirmationVm`, and
  `ModeledCrudCommands` have no public disposal member. VMx does not treat them
  as disposable. Adding one is a separate API decision with its own inventory
  row and conformance coverage.
- VM families, including modeled composite and forwarding, dispose through
  `VmNode::dispose`. It returns `Ok(())` on a repeated call with no new work.
- A VM sends one `Disposed` message. It releases children, LIFO owned
  registrations, and its property-change stream. Illegal lifecycle calls return
  `VmxError::Disposed`.
- `MessageHub` claims disposal under its state mutex. It removes subscribers and
  drops queued messages instead of completing a stream.
- `Subscription` and `PropertyChangedSubscription` are the hub subscription
  handles; `Drop` is a safety net. `ValueStream` and `ValueSubscription` are
  the value streams.
- `RelayCommand` and `RelayCommandOf` release command state.
- `AsyncRelayCommand`, `CompositeCommand`, `DecoratorCommand`, and
  `ConfirmationDecoratorCommand` claim disposal through an atomic disposed
  state.
- `CompositeCommand` and `DecoratorCommand` dispose their change hub once and
  release child-hub subscriptions. Clones share the disposed state.
- `ConfirmationDecoratorCommand` disposes its error hub once and releases error
  subscribers. Confirmation and execution are inert.
- `DerivedProperty`, `ExpandableState`, `SearchableState`, and
  `DiscriminatorVm` dispose their hubs once instead of completing streams.
  `DiscriminatorVm` also disposes its key stream. `DerivedProperty` recompute
  is inert.
- `FilteredCompositeVm` covers predicate and scored projections. It captures
  the frozen projection once and releases projection tracking state.
- `TokenPagedComposition` claims disposal through a shared disposed gate. Its
  owned commands enter a terminal disabled state. Late work cannot commit pager
  state.
- `NotificationHub` claims disposal atomically and keeps one terminal pending
  snapshot. Waiters read `Pending`; post returns a pending result; resolve
  cannot re-enqueue.
- `FormVm` enters a terminal inert state. It releases its command gate and
  approval callbacks; new approval subscriptions are inactive.
- `ModalVm` sets its result once.
- `AggregateChangeSubscription` detaches one output subscription.
  `AggregateChangeStream::batch` panics after disposal.

## 6.8.6. Practical Teardown Pattern

Register every real teardown path and call disposal unconditionally:

```text
page unload ─┐
route switch ├─> root.dispose()
test cleanup ┘
```

Do not add a second consumer-side disposed flag merely to serialize those
paths. Keep ownership explicit: dispose the root and any independently owned
services, but do not dispose caller-owned objects through non-owning wrappers.

The owned-resource contract is covered by `DISP-007..013` and ADR-0090. Inert
modeled assignment is covered by `DISP-014` and ADR-0091.
