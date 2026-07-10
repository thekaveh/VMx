# 6.6. Services, Messages & Dispatching

## When To Use It

Use this layer when the question is coordination rather than structure:
cross-VM messages, scheduler choice, host dialogs, notification routing, or
null-object defaults for headless code and tests.

## Shape And Ownership

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

## Lifecycle And Messaging

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

## Cross-Language Surface

| Service            | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `IMessageHub`      | hot pub/sub for framework messages                   |
| `IDispatcher`      | foreground/background scheduler pair                 |
| `IDialogService`   | request/response host dialogs and modal presentation |
| `INotificationHub` | fire-and-forget notification stream                  |

## Hub Transactions

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

### Composing With Collection Batches

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

### Tableau Migration And Performance Trace

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

## Example

The Quickstart flow shows the minimal service pair every VM needs:

=== "Python"

    ```python
    hub = MessageHub()
    dispatcher = RxDispatcher.immediate()
    ```

From there, higher-level examples add `INotificationHub` and `IDialogService`
only where the workflow requires them.

## Common Pitfalls

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

## Related Primitives

- [NotificationVM](viewmodel-families/specialized/notification-vm.md)
- [ModalVM](viewmodel-families/specialized/modal-vm.md)
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
