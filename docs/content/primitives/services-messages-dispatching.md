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
- `CollectionChangedMessage`, which the hub-aware collections,
  `ObservableDictionary`, and the `CompositeVM` and `GroupVM` containers send
  (containers: one message per local change, and one `Reset` per batch that
  changes the collection, ADR-0142)

## 6.6.3. Lifecycle And Messaging

Important runtime rules from the spec:

- the message hub is hot and non-replaying
- single-producer send order is FIFO
- subscriber exceptions do not break the hub
- transactions defer every typed message until the outermost scope exits;
  messages are preserved and drained FIFO rather than merged
- subscriber-generated messages append to the current iterative drain instead
  of recursively re-entering the Rx subject
- property-changed and collection-changed emissions go to the foreground. An
  implementation either sends them on the foreground dispatcher, or lets
  subscribers observe them on the foreground (spec/11 §3)
- background lifecycle work publishes intermediate state immediately. It sends
  the terminal completion on the foreground
- in Rust, a container with background children stays transient until those
  children settle. Thus `construct()` can return `Ok` while the container is
  still transient. Rust containers report background child failures on
  `background_errors()`

Thread-safe hubs atomically claim teardown, so racing callers still complete
and clear owned state once. See the [Disposal Contract](disposal-contract.md).

No hub retains the messages it delivers. A test or diagnostic that needs to
inspect traffic opts in: Rust attaches a bounded `MessageRecorder` with
`hub.record(capacity)`, and TypeScript wraps a hub in `RecordingMessageHub` from
`@thekaveh/vmx/testing`. A recorder sees each accepted message in delivery order
and never changes delivery (ADR-0141).

Rust dialog, modal, notification-waiter, and confirmation-gate awaitables use
`AsyncValue<T>`. The handle implements `Future` for async hosts and `wait()` for
synchronous hosts, keeping the core independent of Tokio or another executor.

### 6.6.3.1. Application Request Messages

A request from a view-model to its host, such as a navigation request, is an
application message type. The hub carries any `IMessage`, so VMx adds no
request family:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#request-message -->

```typescript
// An application message: the hub carries any IMessage.
class NavigateRequest implements IMessage {
  constructor(
    readonly sender: unknown,
    readonly senderName: string,
    readonly route: string,
  ) {}
}
```

The host subscribes to that type and acts on each request:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#request-host -->

```typescript
// Subscribe the host before any view-model can send a request.
const host = hub.messages
  .pipe(filter((m): m is NavigateRequest => m instanceof NavigateRequest))
  .subscribe((request) => router.navigate(request.route));

hub.send(new NavigateRequest(toolbar, toolbar.name, "/settings"));
```

Requests follow the hub delivery rules. Rust adds one limit:

- **No replay.** The hub is hot. A request sent before the host subscribes is
  lost. Subscribe the host before any view-model can send a request.
- **Every subscriber receives it.** The hub picks no handler and returns no
  reply. If two hosts subscribe, both act on the request.
- **Rust.** `Message::Custom` has only the sender fields and a `name`, so a
  Rust request carries no payload (#673).

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

### 6.6.5.1. Watching Several Properties Of One Source

`whenPropertyChanged` matches one property name. To watch several properties of
one source, own one subscription per name. The header below publishes a
`label` change when the editor's `title` or `dirty` property changes:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#watch-properties -->

```typescript
class HeaderVM extends ComponentVMBase {
  readonly #editor: EditorVM;

  constructor(editor: EditorVM, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "header", hub, dispatcher });
    this.#editor = editor;
    // One owned subscription per watched property of the source.
    for (const name of ["title", "dirty"]) {
      this.own(
        whenPropertyChanged(editor.hub, editor, name).subscribe(() =>
          this._notifyPropertyChanged("label"),
        ),
      );
    }
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get label(): string {
    return this.#editor.dirty ? `${this.#editor.title} *` : this.#editor.title;
  }
}
```

In TypeScript, one subscription can combine `isPropertyChanged` with a set of
names (ADR-0094). Pass the subscription to `own()`, or unsubscribe it when you
dispose its owner:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#watch-properties-predicate -->

```typescript
const watched = new Set(["title", "dirty"]);
const subscription = editor.hub.messages
  .pipe(filter((m) => isPropertyChanged(m, { sender: editor }) && watched.has(m.propertyName)))
  .subscribe(() => refreshHeader());
```

Use one of these two forms until #664 ships.

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

### 6.6.6.1. Observing Same-Value Republishes

The default equality hides a same-reference republish. `republishModel()` sends
a `model` message for the retained model, and `Object.is` reports no change.
The selector still runs for each property message from the source (SUBV-002,
ADR-0095 §3). An equality that always returns `false` therefore calls the
callback for each property message from the source, including messages for
other properties:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#republish -->

```typescript
const renders: Note[] = [];
const subscription = subscribeValue(
  note,
  (vm) => vm.model,
  (model) => renders.push(model),
  // Never equal: each property message from `note` calls the callback.
  { equality: () => false },
);

note.model.title = "Edited in place";
note.republishModel(); // same reference as before
```

### 6.6.6.2. Binding Nested Values

A child view-model sends its own property messages. Bind to the child directly.
The parent does not need to re-announce, or bubble, the child's changes:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#nested-child -->

```typescript
// The child sends its own PropertyChangedMessage. Bind to it directly.
const subscription = subscribeValue(panel.chart, (chart) => chart.plot, draw);
```

A selector can also read across view-models on one hub. In React,
`useVmx(store, () => panel.chart.plot)` runs its selector again after each
message on the store's hub, so the child's message updates the view. See
[React Integration](../integration/react.md).

## 6.6.7. Hub Transactions

Use a hub transaction when one logical operation mutates several viewmodels and
observers must not see intermediate state (ADR-0082). The API is idiomatic
per flavor:

| Flavor     | Transaction scope                    |
| ---------- | ------------------------------------ |
| C#         | `hub.Batch(() => { ... })`           |
| Python     | `with hub.batch(): ...`              |
| TypeScript | `hub.batch(() => { ... })`           |
| Swift      | `try hub.batch { ... }`              |
| Rust       | `hub.batch(|| { ... })`              |

In C#, `Batch` is on `ITransactionalMessageHub`, which `MessageHub` implements.
A variable typed as `IMessageHub` must be a `MessageHub` or an
`ITransactionalMessageHub` to call it.

The scope is lossless. If it sends `A`, `B`, and `C`, every current subscriber
receives `A`, `B`, and `C` exactly once after the outermost scope exits. Nested
scopes flatten. If the body raises, queued messages drain first and the original
error is then rethrown. Disposing the hub clears the undelivered queue.

An ordinary top-level send is synchronous. If a subscriber sends another
message, that message waits behind the in-flight message. All subscribers
therefore finish `A` before any starts `B`.

Threaded flavors serialize another producer behind the active transaction. They
then deliver on that producer's calling thread, also from inside a callback.
Unrelated busy targets therefore still wait synchronously.

The only exception is an actual cross-hub thread wait cycle (ADR-0119). The
send that would close the cycle enqueues and returns to the active owner's
drain. A disposal in that position records terminal intent for the owner to
finish. A cyclic batch borrows the target until its body exits, so the owner
cannot resume draining early.

Keep transaction bodies short. Never wait for a thread that is itself trying to
send through the same hub.

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

In the samples below, `notes` is a hub-connected `CompositeVM` of note
viewmodels, and `first` and `second` are note viewmodels.

=== "C#"

    ```csharp
    hub.Batch(() =>
    {
        using (notes.BatchUpdate())
        {
            notes.Add(first);
            notes.Add(second);
        }
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
      const update = notes.batchUpdate();
      try {
        notes.add(first);
        notes.add(second);
      } finally {
        update.dispose();
      }
      summary.model = buildSummary(notes);
    });
    ```

### 6.6.7.2. Coalescing Host Refresh

A hub transaction stays lossless, so a host adapter coalesces expensive work
itself. Wrap command-side multi-VM mutations in `hub.batch(...)`. Then schedule
one invalidation for the synchronous drain:

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

For a transaction that publishes `N` messages to `S` subscribers, the hub
performs `N × S` message callbacks; it discards no typed event. All `N`
callbacks occur in one synchronous drain. A host adapter can therefore collapse
expensive rendering or derived-state refresh from `N` executions to one. It
keeps the full event stream.

## 6.6.8. Example

The Quickstart flow shows the minimal service pair every VM needs:

=== "Python"

    ```python
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    ```

From there, higher-level examples add `INotificationHub` and `IDialogService`
only where the workflow requires them.

## 6.6.9. Python asyncio dispatcher ownership

`RxDispatcher.asyncio(loop)` uses RxPY's
`AsyncIOThreadSafeScheduler(loop)` as its foreground scheduler, so background
lifecycle completion can safely wake and run on the supplied asyncio loop. The
host must capture that loop while it is running; VMx neither runs nor closes a
caller-provided loop. This scheduler gives terminal emissions host-loop
affinity, not general thread-safe VM mutation.

The `ThreadPoolScheduler` background executor is independent of asyncio's
default executor. The composition root must stop new submissions and await
admitted background hooks while the loop is still responsive before it
synchronously disposes VMs or subscriptions; disposal can wait for an active
foreign hook. It then shuts down the pool from outside that pool. An async host
can encode that order with its own admission tracker:

```python
import asyncio

from reactivex.scheduler import ThreadPoolScheduler


async def close_vmx(
    dispatcher, vms, subscriptions, stop_submissions, wait_for_background
) -> None:
    # Keep the loop responsive until all previously admitted hooks settle.
    stop_submissions()
    await wait_for_background()

    pool = dispatcher.background
    try:
        # It is now safe to synchronously release host-owned VMx resources.
        for subscription in subscriptions:
            subscription.dispose()
        for vm in vms:
            vm.dispose()
    finally:
        if isinstance(pool, ThreadPoolScheduler):
            await asyncio.to_thread(pool.executor.shutdown, wait=True)
```

Only close an event loop that the host created and owns. Desktop toolkits with
their own UI queue, such as Tkinter, need a host-owned foreground bridge for
background producers; an asyncio loop on another thread is not the Tk UI
thread.

### 6.6.9.1. Async Resource Operation Loops

A synchronous caller may launch Python `AsyncResourceVM` through
`load_command.execute()` without owning a running loop on that thread. VMx then
starts the operation on its shared daemon loop. Each resource
operation records the loop that created its loader task and cancellation
future. Direct `cancel()` or `dispose()` invalidates the resource generation and
state immediately; cancellation-future completion, loader-task cancellation,
and late callback registration execute on the recorded operation loop. The
linked async command can settle after that synchronous invalidation.

Operation-loop ownership does not dispatch state notifications, cleanup
callbacks, or arbitrary VM calls to a UI thread. Those retain the normal
dispatcher and calling-context contracts. An open stopped operation loop queues
native work until it restarts. If an application owns the loop, it must stop
new admissions, cancel resource work, and drain it while that loop can still
run before closing the loop. Once a loop is closed, VMx cannot finish pending
tasks, deliver callbacks discarded by closure, or force coroutine `finally`
blocks. The shared daemon loop used by the no-loop command fallback is VMx
infrastructure; applications do not close it.

The tracked
[`langs/python/tests/unit/state/test_async_resource_threading.py`](../../../langs/python/tests/unit/state/test_async_resource_threading.py)
executes the synchronous launch plus caller-thread cancellation and disposal:

```bash
cd langs/python
PYTHONASYNCIODEBUG=1 uv run pytest \
  tests/unit/state/test_async_resource_threading.py::test_no_loop_command_caller_cancels_on_operation_loop \
  -q
```

See [State & Reactive Helpers](state-reactive-helpers.md#653-async-resource-state)
for acquisition ownership and the [Disposal Contract](disposal-contract.md) for
terminal cleanup.

## 6.6.10. Common Pitfalls

- Treating the hub like a replaying event store. It is hot and current-subscriber
  only.
- Reading Rust's deprecated `MessageHub::history()`, which is always empty.
  Attach a `MessageRecorder` before the sends to inspect.
- Treating a hub transaction as message deduplication. It defers and orders;
  host adapters decide whether expensive rendering should be coalesced.
- Waiting inside a transaction for another thread that must send through the
  same hub.
- Assuming background lifecycle completion arrives on a background thread in
  consumers. Terminal completion is foreground-marshalled by the reference
  implementations.
- Using dialogs for fire-and-forget notifications or using notification hubs for
  blocking user decisions.

## 6.6.11. Related Primitives

- [NotificationVM](viewmodel-families/specialized/notification-vm.md)
- [ModalVM](viewmodel-families/specialized/modal-vm.md)
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
