# 6.8. Disposal Contract

VMx disposal is safe to call from independent teardown paths. If a public
VMx-owned type exposes `Dispose()` / `dispose()`, the first call claims its
terminal work and every later or re-entrant call is a no-op. Completion,
terminal notifications, cancellation, and owned-resource cleanup happen at
most once.

This rule removes the need for host-side “already disposed” flags. It does not
make all later API calls behave alike: each type keeps its documented
post-dispose behavior.

## Modeled Assignment After Disposal

Modeled assignment has one portable terminal rule across all five flavors. If
an assignment begins after the VM is disposed, it returns before candidate
equality, retained-model or snapshot mutation, modeled-hint work, validation,
command-state recomputation, consumer callbacks, local notifications, or hub
messages. The last accepted model and every derived state value remain
readable and unchanged.

This admission guard covers modeled components and `FormVM`. Swift's internal
read-only modeled-component update and forwarding wrappers delegate to the same
guarded path. Modeled composites do not expose a settable retained model—their
model input configures a child factory—so they need no separate guard.

An assignment admitted before disposal keeps its ordinary completion and
notification contract. Continue cancelling network requests, renderer work,
tasks, and other application operations when their resources are no longer
needed; the VM guard prevents late state admission but does not replace
resource cancellation.

## The Six Disposal Families

| Family                        | Representative surfaces                                             | Cross-cutting ID | Existing detailed coverage                        |
| ----------------------------- | ------------------------------------------------------------------- | ---------------- | ------------------------------------------------- |
| VM and owner cascades         | Component, composite, group, aggregate, hierarchy, forwarding       | `DISP-001`       | `LIFE-004`, `LIFE-012`, `LIFE-013`                |
| Commands                      | Relay, async relay, composite/decorator, modeled CRUD               | `DISP-002`       | `CMD-012`, `CMD-013`, `CMDD-010`                  |
| Hubs and services             | Message hub, notification hub                                       | `DISP-003`       | `HUB-012`, `NOTIF-017`                            |
| Interaction owners            | Form, modal, notification rendering VMs                             | `DISP-004`       | `DIA-011`, `DIA-012`, `FORM-014`, `NOTIF-017`     |
| Reactive helpers              | Derived property, expansion/search state, discriminator             | `DISP-005`       | `DPROP-011`, `COMP-035`, `CVM-009`                |
| Collection/projection helpers | Batch handles, paging, filtered projections, disposable collections | `DISP-006`       | `COMP-013`, `GRP-006`, `COL-024..031`, `COMP-035` |

Only types already documented as thread-safe promise racing disposal. Those
types atomically claim terminal work. Single-threaded flavors and helpers still
guarantee repeated and re-entrant disposal on their supported execution model.

## Ownership Rules

- Every VM exposes its injected message hub as a read-only baseline member. The
  hub is shared infrastructure: VM disposal never disposes it.
- Subclass-owned, disposal-lifetime resources can be registered through
  `Own` (C#), `_own` (Python), or `own` (TypeScript, Swift, Rust). Cleanup is
  exactly once in LIFO order after the subclass disposal hook. One failing
  cleanup is swallowed without blocking the rest.
- Registration after disposal cleans the resource immediately once.
- Reconstruct and destruct do not release disposal-lifetime registrations.
  Per-construct resources remain explicit in `OnConstruct`/`OnDestruct`.
- Parent VMs dispose owned children depth-first. A child reached through
  several teardown paths has one observable terminal transition.
- A forwarding VM delegates disposal to the wrapped VM; it does not introduce
  reference counting.
- Command decorators and composites do not dispose caller-owned inner commands
  unless their type-specific contract explicitly says they own them.
- `ServicedObservableCollection` and `KeyedServicedObservableCollection` never
  own or dispose their items and do not implement VM child-collection lifecycle
  interfaces.
- Subscription and batch handles release only the registration or batch scope
  they represent.

## C# Inventory

| Public disposable surface                                                                       | Second dispose                   | Completion / terminal signal                                     | Owned teardown                                                                      | Permitted post-dispose behavior                                                                     |
| ----------------------------------------------------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `IComponentVM` implementations: component, readonly, composite, group, aggregate 1–6, hierarchy | No-op                            | One `Disposed` transition; VM-local streams complete             | Subclass hook, LIFO owned registrations, commands, and children per family ordering | Status reads remain; lifecycle calls other than dispose raise; selection/property changes are inert |
| `ForwardingComponentVM`, `ForwardingCompositeVM`                                                | Delegated no-op                  | Wrapped VM completes once                                        | Delegates to wrapped VM                                                             | Wrapped VM contract                                                                                 |
| `MessageHub`                                                                                    | No-op under its gate             | `Messages` completes once                                        | Pending transaction queue and subject                                               | Sends are ignored after disposal                                                                    |
| `RelayCommand`, `RelayCommand<T>`                                                               | No-op                            | Optional final `CanExecuteChanged`; then terminal disabled state | Trigger subscriptions                                                               | `CanExecute == false`; execute is inert                                                             |
| `AsyncRelayCommand`                                                                             | No-op under its gate             | Error channel completes once                                     | Cancels one active token and trigger subscriptions                                  | Disabled; later execute is inert                                                                    |
| `CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`, `ModeledCrudCommands`   | No-op                            | Owned error channel completes where present                      | Event subscriptions and owned relay commands only                                   | Inert according to command type; caller-owned inner commands remain caller-owned                    |
| `FormVM<T>`                                                                                     | No-op                            | Approval/error/validation channels complete once                 | Approve/deny commands                                                               | Approve and deny are inert; readable model/snapshot state remains                                   |
| `NotificationHub`                                                                               | No-op under its lock             | Pending completes once; waiters resolve `Pending`                | Pending queue and waiters                                                           | Post resolves `Pending`; resolve is inert                                                           |
| `NotificationVM`, `ConfirmationVM`                                                              | No-op                            | Property-change surface stops                                    | Timers, pending subscription, commands                                              | Last render state remains readable; later resolution paths are inert                                |
| `ModalVM<T>`                                                                                    | No-op through idempotent dismiss | Completion resolves once                                         | Waiter completion                                                                   | First result remains readable                                                                       |
| `DerivedProperty<T>`                                                                            | No-op                            | `ValueChanged` completes once                                    | Source subscriptions                                                                | Last value remains readable; writes follow the type-specific validator contract                     |
| `ExpandableState`, `SearchableState<T>`                                                         | No-op                            | Helper streams complete once                                     | Search/source subscriptions                                                         | Retained state is readable; no further emissions                                                    |
| `FilteredCompositeVM`, `ScoredFilteredCompositeVM`                                              | No-op                            | Projection stops changing                                        | Source collection subscription                                                      | Frozen visible projection remains readable                                                          |
| `PagedComposition<T>`                                                                           | No-op                            | No completion surface                                            | Source collection subscription                                                      | Page reads remain available without source tracking                                                 |
| `TokenPagedComposition<T,TToken>`                                                               | No-op under its gate             | Command stream completes once                                    | Load/refresh commands                                                               | Late fetch results cannot mutate or publish                                                         |
| Public batch-return handles from list/composite/group operations                                | No-op                            | At most one reset at outer batch exit                            | One batch depth claim                                                               | Handle has no other behavior                                                                        |
| `DiscriminatorVM<TKey>`                                                                         | No-op                            | Active-change stream completes once                              | Stream subject                                                                      | Reads remain; later mutations are inert                                                             |

## Python Inventory

| Public disposable surface                                                              | Second dispose                   | Completion / terminal signal                      | Owned teardown                                                | Permitted post-dispose behavior                                                |
| -------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Component/composite/group/aggregate/hierarchy VM families                              | No-op under the lifecycle lock   | One `DISPOSED` transition; local streams complete | Subclass hook, LIFO owned registrations, commands, children   | Status reads remain; illegal lifecycle calls raise; changes are inert          |
| Forwarding component/composite VMs                                                     | Delegated no-op                  | Wrapped VM completes once                         | Delegates to wrapped VM                                       | Wrapped VM contract                                                            |
| `MessageHub`                                                                           | No-op under its lock             | `messages` completes once                         | Pending transaction queue and subject                         | Sends are ignored                                                              |
| Relay, async relay, composite/decorator, confirmation-decorator, modeled-CRUD commands | No-op                            | Owned subjects complete once                      | Trigger subscriptions; one in-flight async task; owned relays | Disabled/inert after disposal; caller-owned inner commands remain caller-owned |
| `FormVM`                                                                               | No-op                            | Approval/error/validation streams complete once   | Approve/deny commands                                         | Approve and deny are inert; model/snapshot remain readable                     |
| `NotificationHub`                                                                      | No-op under its lock             | Pending completes once; futures resolve `PENDING` | Pending queue and futures                                     | Post resolves `PENDING`; resolve is inert                                      |
| `NotificationVM`, `ConfirmationVM`                                                     | No-op                            | Property-change stream completes once             | Timers, subscriptions, commands                               | Last render state remains readable                                             |
| `ModalVM`                                                                              | No-op through idempotent dismiss | Waiters resolve once                              | Awaiting futures                                              | First result remains readable                                                  |
| `DerivedProperty`                                                                      | No-op                            | `value_changed` completes once                    | Source subscriptions                                          | Last value remains readable; no recompute emission                             |
| `ExpandableState`, `SearchableState`                                                   | No-op                            | Helper streams complete once                      | Search/source subscriptions                                   | Retained state is readable; no emissions                                       |
| `FilteredCompositeVM`, `ScoredFilteredCompositeVM`                                     | No-op                            | Projection stream completes once                  | Source subscription                                           | Frozen projection remains readable                                             |
| `PagedComposition`, `TokenPagedComposition`                                            | No-op                            | Paging streams complete where exposed             | Source subscriptions and paging commands                      | Reads remain; late token fetches cannot mutate                                 |
| `ObservableList`, `ObservableDictionary`                                               | No-op                            | Every VMx-owned collection subject completes once | Collection subjects                                           | Stored contents remain readable; mutations emit nothing                        |
| `BatchUpdateHandle`                                                                    | No-op                            | At most one reset at outer batch exit             | One batch depth claim                                         | Handle has no other behavior                                                   |
| `DiscriminatorVM`                                                                      | No-op                            | Active-change stream completes once               | Stream subject                                                | Reads remain; later mutations are inert                                        |

## TypeScript Inventory

| Public disposable surface                                                              | Second dispose                   | Completion / terminal signal                       | Owned teardown                                              | Permitted post-dispose behavior                                       |
| -------------------------------------------------------------------------------------- | -------------------------------- | -------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------- |
| Component/composite/group/aggregate/hierarchy VM families                              | No-op                            | One `Disposed` transition; local streams complete  | Subclass hook, LIFO owned registrations, commands, children | Status reads remain; illegal lifecycle calls throw; changes are inert |
| Forwarding component/composite VMs                                                     | Delegated no-op                  | Wrapped VM completes once                          | Delegates to wrapped VM                                     | Wrapped VM contract                                                   |
| `MessageHub`                                                                           | No-op                            | `messages` completes once                          | Pending transaction queue and subject                       | Sends are ignored                                                     |
| Relay, async relay, composite/decorator, confirmation-decorator, modeled-CRUD commands | No-op                            | Owned subjects complete once                       | Trigger subscriptions; one `AbortController`; owned relays  | Disabled/inert; caller-owned inner commands remain caller-owned       |
| `FormVM`                                                                               | No-op                            | Approval/error/validation streams complete once    | Approve/deny commands                                       | Approve and deny are inert; state remains readable                    |
| `NotificationHub`                                                                      | No-op                            | Pending completes once; promises resolve `Pending` | Pending queue and resolvers                                 | Post resolves `Pending`; resolve is inert                             |
| `NotificationVM`, `ConfirmationVM`                                                     | No-op                            | Property-change stream completes once              | Scheduler handles, subscriptions, commands                  | Last render state remains readable                                    |
| `ModalVM`                                                                              | No-op through idempotent dismiss | Promise resolves once                              | Completion resolver                                         | First result remains readable                                         |
| `DerivedProperty`                                                                      | No-op                            | `valueChanged` completes once                      | Source subscription                                         | Last value remains readable; no recompute emission                    |
| `ExpandableState`, `SearchableState`                                                   | No-op                            | Helper streams complete once                       | Search/source subscriptions                                 | Retained state is readable; no emissions                              |
| `FilteredCompositeVM`, `ScoredFilteredCompositeVM`                                     | No-op                            | Projection stream completes once                   | Source subscription                                         | Frozen projection remains readable                                    |
| `PagedComposition`, `TokenPagedComposition`                                            | No-op                            | Paging streams complete where exposed              | Source subscriptions and paging commands                    | Reads remain; late token fetches cannot mutate                        |
| `BatchUpdateHandle` / `[Symbol.dispose]`                                               | No-op                            | At most one reset at outer batch exit              | One batch depth claim                                       | Handle has no other behavior                                          |
| `DiscriminatorVM`                                                                      | No-op                            | Active-change stream completes once                | Stream subject                                              | Reads remain; later mutations are inert                               |

## Swift Inventory

| Public disposable surface                                                              | Second dispose                   | Completion / terminal signal                           | Owned teardown                                              | Permitted post-dispose behavior                                       |
| -------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------------------------------- |
| Component/composite/group/aggregate/hierarchy VM families                              | No-op under the lifecycle lock   | One `.disposed` transition; local publishers finish    | Subclass hook, LIFO owned registrations, commands, children | Status reads remain; illegal lifecycle calls throw; changes are inert |
| Forwarding component/composite VMs                                                     | Delegated no-op                  | Wrapped VM finishes once                               | Delegates to wrapped VM                                     | Wrapped VM contract                                                   |
| `MessageHub`                                                                           | No-op under its lock             | `messages` finishes once                               | Pending transaction queue                                   | Sends are ignored                                                     |
| Relay, async relay, composite/decorator, confirmation-decorator, modeled-CRUD commands | No-op                            | Owned publishers finish once                           | Cancellables; one active task; owned relays                 | Disabled/inert; caller-owned inner commands remain caller-owned       |
| `FormVM`                                                                               | No-op                            | Approval/error/validation publishers finish once       | Approve/deny commands                                       | Approve and deny are inert; state remains readable                    |
| `NotificationHub`                                                                      | No-op under its lock             | Pending finishes once; continuations resume `.pending` | Pending queue and continuations                             | Post returns `.pending`; resolve is inert                             |
| `NotificationVM`, `ConfirmationVM`                                                     | No-op                            | Property-change publisher finishes once                | Timer, tick, pending subscription, commands                 | Last render state remains readable                                    |
| `BasicModalVM`                                                                         | No-op through idempotent dismiss | Continuations resume once                              | Awaiting continuations                                      | First result remains readable                                         |
| `DerivedProperty`                                                                      | No-op                            | `valueChanged` finishes once                           | Source cancellables                                         | Last value remains readable; no recompute emission                    |
| `ExpandableState`, `SearchableState`                                                   | No-op                            | Helper publishers finish once                          | Search/source cancellables                                  | Retained state is readable; no emissions                              |
| `FilteredCompositeVM`, `ScoredFilteredCompositeVM`                                     | No-op                            | Projection publisher finishes once                     | Source cancellables                                         | Frozen projection remains readable                                    |
| `TokenPagedComposition`                                                                | No-op on its state queue         | Collection/property/command publishers finish once     | Paging commands                                             | Late fetch results cannot mutate                                      |
| `BatchUpdateHandle`                                                                    | No-op                            | At most one reset at outer batch exit                  | One batch depth claim                                       | Handle has no other behavior; `deinit` is a safety net                |
| `DiscriminatorVM`                                                                      | No-op                            | Active-change publisher finishes once                  | Publisher subject                                           | Reads remain; later mutations are inert                               |

`PagedComposition`, `ObservableList`, and `ObservableDictionary` do not expose a
VMx disposal member in Swift; they are therefore outside this invariant's
public-disposable inventory.

## Rust Inventory

| Public disposable surface                                                                                    | Second dispose                      | Completion / terminal signal                          | Owned teardown                                                 | Permitted post-dispose behavior                                                             |
| ------------------------------------------------------------------------------------------------------------ | ----------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `VmNode::dispose`: component, composite, group, modeled composite, hierarchy, aggregate, forwarding families | `Ok(())` with no new work           | One `Disposed` message                                | LIFO owned registrations, children, and property-change stream | Status reads remain; illegal lifecycle calls return `VmxError::Disposed`; changes are inert |
| `MessageHub`                                                                                                 | No-op under its state mutex         | Subscribers are removed; queued messages are dropped  | Subscribers and pending transaction queue                      | Sends are ignored                                                                           |
| `Subscription`, `PropertyChangedSubscription`                                                                | No-op                               | No completion surface                                 | One subscriber registration                                    | Handle has no other behavior; `Drop` is a safety net                                        |
| `RelayCommand`, `RelayCommandOf`                                                                             | No-op                               | Terminal disabled state                               | Command state                                                  | `can_execute == false`; execute is inert                                                    |
| `AsyncRelayCommand`                                                                                          | No-op through atomic disposed state | One active token is cancelled                         | Active cancellation token                                      | Disabled; later execute is inert                                                            |
| `FilteredCompositeVm`                                                                                        | No-op                               | Frozen projection captured once                       | Projection tracking state                                      | Frozen projection remains readable                                                          |
| `DerivedProperty`                                                                                            | No-op                               | Value-change hub is disposed once                     | Value-change subscribers                                       | Last value remains readable; recompute is inert                                             |
| `NotificationHub`                                                                                            | No-op after an atomic claim         | One terminal pending snapshot; waiters read `Pending` | Pending notifications                                          | Post returns a pending result; resolve cannot re-enqueue                                    |
| `FormVm`                                                                                                     | No-op                               | Terminal inert state                                  | Form command gate                                              | Approve/deny are inert; state remains readable                                              |
| `ModalVm`                                                                                                    | No-op through idempotent dismiss    | Result is set once                                    | Result state                                                   | First result remains readable                                                               |

Rust types without a public disposal member—such as `PagedComposition`,
`SearchableState`, `ExpandableState`, `DiscriminatorVm`, rendering
`NotificationVm`, and token paging—are not silently treated as disposable.
Adding such a surface is a separate API decision and would require its own
inventory row and conformance coverage.

## Practical Teardown Pattern

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
