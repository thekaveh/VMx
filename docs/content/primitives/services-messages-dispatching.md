# 6.6. Services, Messages & Dispatching

## 6.6.1. When To Use It

Use this layer when the question is coordination rather than structure:
cross-VM messages, scheduler choice, host dialogs, notification routing, or
null-object defaults for headless code and tests.

## 6.6.2. Shape And Ownership

The core services are:

- `IMessageHub` / `MessageHub`
- the additive transaction capability (`ITransactionalMessageHub` /
  `TransactionalMessageHubProto` / `TransactionalMessageHubProtocol`)
- `IDispatcher` / `RxDispatcher`
- `IDialogService`
- `INotificationHub` in the opt-in notifications package
- null variants for the service contracts

The core message families are:

- `PropertyChangedMessage`
- `ConstructionStatusChangedMessage`
- `TreeStructureChangedMessage`
- `FormRevertedMessage`
- collection-changed messages from the collections area

## 6.6.3. Lifecycle And Messaging

Important runtime rules from the spec:

- the message hub is hot and non-replaying
- single-producer send order is FIFO
- subscriber exceptions do not break the hub
- transactions defer every typed message until the outermost scope exits;
  messages are preserved and drained FIFO rather than merged
- subscriber-generated messages append to the current iterative drain instead
  of recursively re-entering the Rx subject
- property-changed and collection-changed emissions are foreground-dispatched by
  contract when the implementation marshals them that way
- background lifecycle work publishes intermediate state immediately and
  foreground-marshals terminal completion

Thread-safe hubs atomically claim teardown, so racing callers still complete
and clear owned state once. See the [Disposal Contract](disposal-contract.md).

Rust dialog, modal, notification-waiter, and confirmation-gate awaitables use
`AsyncValue<T>`. The handle implements `Future` for async hosts and `wait()` for
synchronous hosts, keeping the core independent of Tokio or another executor.

## 6.6.4. Cross-Language Surface

| Service            | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `IMessageHub`      | hot pub/sub for framework messages                   |
| `IDispatcher`      | foreground/background scheduler pair                 |
| `IDialogService`   | request/response host dialogs and modal presentation |
| `INotificationHub` | fire-and-forget notification stream                  |

## 6.6.5. TypeScript Raw-Message Narrowing

TypeScript exports three predicates for classifying mixed raw `IMessage`
streams and arrays. Their unary overloads can be passed directly to RxJS or
array filters; an inline constraint object adds exact sender/source and
family-specific matching. Sender and source matching uses object identity.

```typescript
import {
  ConstructionStatus,
  isCollectionChanged,
  isConstructionStatusChanged,
  isPropertyChanged,
  ServicedObservableCollection,
} from "@thekaveh/vmx";
import { filter } from "rxjs";

interface Note {
  readonly title: string;
}

const notes = new ServicedObservableCollection<Note>(hub);

const propertyChanges = hub.messages.pipe(filter(isPropertyChanged));

const modelChanges = hub.messages.pipe(
  filter((message) =>
    isPropertyChanged(message, { sender: vm, propertyName: "model" }),
  ),
);

const addedNotes = hub.messages.pipe(
  filter((message) =>
    isCollectionChanged(message, {
      source: notes,
      action: "add",
    }),
  ),
);

const constructed = hub.messages.pipe(
  filter((message) =>
    isConstructionStatusChanged(message, {
      sender: vm,
      status: ConstructionStatus.Constructed,
    }),
  ),
);
```

The sender generic is inferred only when a sender constraint is supplied and
checked. Collection predicates always retain `CollectionChangedMessage<unknown>`,
even when the source is a typed `ServicedObservableCollection<TItem>`: source
identity cannot prove a payload type because public message factories accept
sender and item types independently. An explicitly present `undefined`
constraint is compared exactly, while an omitted field is ignored.

Use `whenPropertyChanged(hub, sender, propertyName)` when those three inputs are
already known and the subscriber needs the matching message. Use
`propertyValueChangedMessagesFor(hub, sender, propertyName)` when it needs the
current property value instead. The raw predicates are the appropriate choice
when classifying a mixed message stream or array, especially when one pipeline
must recognize several message families.

## 6.6.6. Imperative Selected-State Bridge

Use `subscribeValue` when a renderer, audio engine, canvas host, shader bridge,
or other imperative consumer needs selected state from one fixed VM. It
evaluates a selector after every property message from that VM and invokes the
callback only when the selected value changes. This is a change-driven bridge,
not a frame-polling loop.

The idiomatic entry points and teardown handles are:

| Flavor     | Entry point                                                                                                     | Returned handle   | Teardown          |
| ---------- | --------------------------------------------------------------------------------------------------------------- | ----------------- | ----------------- |
| C#         | `source.SubscribeValue(selector, callback, equalityComparer?, fireImmediately?)`                                | `IDisposable`     | `Dispose()`       |
| Python     | `subscribe_value(source, selector, callback, *, equality=None, fire_immediately=False)`                         | `DisposableBase`  | `dispose()`       |
| TypeScript | `subscribeValue(source, selector, callback, { equality?, fireImmediately? })`                                   | `Subscription`    | `unsubscribe()`   |
| Swift      | `subscribeValue(source, selector:, callback:, isEqual:, fireImmediately:)` or the `Equatable` overload          | `AnyCancellable`  | `cancel()`        |
| Rust       | `hub.subscribe_value(sender_id, selector, callback, options)`                                                   | `Subscription`    | `dispose()`       |

Setup is synchronous. The selector runs once to establish the initial value.
With immediate delivery enabled, the callback receives `(initial, initial)`
before the hub subscription is attached. A later change invokes it as
`(current, previous)`. The baseline is updated before the callback, so a
re-entrant source mutation compares against the newest value.

Every matching property message reevaluates the selector once, even when a
different source property triggered the message. Equality then decides whether
to call the callback. Defaults are `EqualityComparer<TValue>.Default`, `==`,
`Object.is`, Swift `Equatable.==`, and Rust `PartialEq`; every flavor also
accepts custom equality. Messages from other senders and non-property message
families never evaluate the selector.

Hub batches stay lossless: the helper examines every matching message. Because
the selector reads current state at delivery time, several queued messages may
all observe the same final snapshot, and equality may reduce those observations
to one callback. That is final-snapshot suppression, not message coalescing.

Initial selector and immediate-callback failures propagate synchronously, and
no subscription is attached. Delivery-time selector, equality, and callback
failures follow the flavor's HUB-007 subscriber-failure path; they cannot break
the hub or another subscriber. A failed callback does not roll back the already
updated baseline.

The callback and everything it captures belong to the host. VMx does not
automatically register the returned handle with the observed VM. Dispose or
cancel it with the host adapter; after teardown, no later message invokes the
selector, equality, or callback.

The source set is deliberately fixed. `subscribeValue` does not discover
collection members, track selector dependencies, or resubscribe when membership
changes. Use `AggregateChangeStream` (ADR-0098) for dynamic member fan-in.

## 6.6.7. Hub Transactions

Use a hub transaction when one logical operation mutates several viewmodels and
observers must not see intermediate state. The API is idiomatic per flavor:

| Flavor     | Transaction scope                    |
| ---------- | ------------------------------------ |
| C#         | `hub.Batch(() => { ... })`           |
| Python     | `with hub.batch(): ...`              |
| TypeScript | `hub.batch(() => { ... })`           |
| Swift      | `try hub.batch { ... }`              |
| Rust       | `hub.batch(|| { ... })`              |

The scope is lossless. If it sends `A`, `B`, and `C`, every current subscriber
receives `A`, `B`, and `C` exactly once after the outermost scope exits. Nested
scopes flatten. If the body raises, queued messages drain first and the original
error is then rethrown. Disposing the hub clears the undelivered queue.

An ordinary top-level send remains synchronous. If a subscriber sends another
message, that message waits behind the in-flight message, so all subscribers
finish `A` before any starts `B`. Threaded flavors serialize another producer
behind the active transaction and then deliver on that producer's calling
thread. Keep transaction bodies short and never wait for a thread that is
itself trying to send through the same hub.

Development builds bound a drain cycle and report the involved message types.
TypeScript detects Node development/test mode automatically; browser adapters
enable the same guard explicitly with
`new MessageHub({ developmentDiagnostics: true })`. Browser defaults stay
unbounded so a production bundle never drops a large finite transaction.

### 6.6.7.1. Composing With Collection Batches

Collection-local batching and hub transactions solve different layers:

- a collection batch replaces several local mutation notifications with its
  defined reset/summary event;
- a hub transaction defers heterogeneous messages from the whole VM graph but
  never removes them.

Put the collection scope inside the hub scope. The collection emits its one
reset into the hub queue, sibling viewmodels enqueue their own typed messages,
and observers receive the complete FIFO only after both scopes close.

=== "C#"

    ```csharp
    hub.Batch(() =>
    {
        using var update = notes.BatchUpdate();
        notes.Add(first);
        notes.Add(second);
        summary.Model = BuildSummary(notes);
    });
    ```

=== "Python"

    ```python
    with hub.batch():
        with notes.batch_update():
            notes.append(first)
            notes.append(second)
        summary.model = build_summary(notes)
    ```

=== "TypeScript"

    ```typescript
    hub.batch(() => {
      notes.withBatch(() => {
        notes.add(first);
        notes.add(second);
      });
      summary.model = buildSummary(notes);
    });
    ```

### 6.6.7.2. Tableau Migration And Performance Trace

Tableau's React store added a hand-written `refreshing` flag after
`refreshShell()` updated derived VM models, republished through the same hub,
and recursively re-entered the store subscription. The incident is preserved in
[`frontend/view/react/src/store.ts`](https://github.com/thekaveh/tableau/blob/main/frontend/view/react/src/store.ts).

The v3.2 contract changes the execution trace without hiding messages:

| Stage                     | Immediate recursive hub                       | v3.2 transaction + iterative drain                    |
| ------------------------- | --------------------------------------------- | ----------------------------------------------------- |
| Three model mutations     | observers run after each intermediate change | zero observer calls until the outer scope exits       |
| Publish stack             | grows with subscriber-generated sends        | stays at one drainer frame                            |
| Message fidelity          | all messages delivered                       | all messages delivered once, FIFO                    |
| Plain subscriber refresh  | up to one refresh per message                | still one per message; batching is intentionally lossless |
| Scheduled host invalidation | consumer-specific                           | one refresh for the synchronous drain                |

For Tableau, wrap command-side multi-VM mutations in `hub.batch(...)` and make
the React adapter schedule one invalidation for the synchronous drain:

```typescript
let invalidationPending = false;
const sub = app.canvas.hub.messages.subscribe(() => {
  if (invalidationPending) return;
  invalidationPending = true;
  queueMicrotask(() => {
    try {
      app.refreshShell();
      version += 1;
      for (const listener of listeners) listener();
    } finally {
      invalidationPending = false;
    }
  });
});
```

For a transaction that publishes `N` messages to `S` subscribers, the hub still
performs `N × S` message callbacks—typed events are not discarded. The useful
performance boundary is that all `N` callbacks occur in one synchronous drain,
so a host adapter can collapse expensive rendering or derived-state refresh
from `N` executions to one while retaining the full event stream.

## 6.6.8. Example

The Quickstart flow shows the minimal service pair every VM needs:

=== "Python"

    ```python
    hub = MessageHub()
    dispatcher = RxDispatcher.immediate()
    ```

From there, higher-level examples add `INotificationHub` and `IDialogService`
only where the workflow requires them.

## 6.6.9. Common Pitfalls

- Treating the hub like a replaying event store. It is hot and current-subscriber
  only.
- Treating a hub transaction as message deduplication. It defers and orders;
  host adapters decide whether expensive rendering should be coalesced.
- Waiting inside a transaction for another thread that must send through the
  same hub.
- Assuming background lifecycle completion arrives on a background thread in
  consumers. Terminal completion is foreground-marshalled by the reference
  implementations.
- Using dialogs for fire-and-forget notifications or using notification hubs for
  blocking user decisions.

## 6.6.10. Related Primitives

- [NotificationVM](viewmodel-families/specialized/notification-vm.md)
- [ModalVM](viewmodel-families/specialized/modal-vm.md)
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
