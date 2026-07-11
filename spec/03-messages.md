# 03 — Messages and the message hub

VMx uses a single hot pub/sub stream — the message hub — to convey property changes,
lifecycle status changes, and any future event types. Subscribers observe via an Rx
`IObservable<IMessage>`.

## 1. `IMessage` shape

Every message implements `IMessage` (rendered per language as `Message`):

```
IMessage:
    SenderName : string
    Sender : object
```

Strongly-typed senders narrow `Sender` via `IMessage<TSender>`:

```
IMessage<TSender> : IMessage:
    Sender : TSender
```

`SenderName` typically equals `Sender.Name`. `Sender` is the runtime sender
instance — the **single canonical sender field** in every flavor (ADR-0006).
On the untyped base it carries no compile-time type information (`object` /
`unknown`, for polymorphic subscribers); `IMessage<TSender>` narrows it to the
concrete `TSender`.

TypeScript exposes `Sender` as its sole sender field as of v3.0.0, having
removed an earlier redundant untyped alias (ADR-0054). C#, Python, and Swift
additionally retain a deprecated untyped alias on the base message
(`IMessage.SenderObject`, `Message.sender_object`, `Message.senderObject`)
for source compatibility; that alias returns the same instance as `Sender`
and is slated for removal at each of those flavors' next major. The canonical
accessor across the full-parity flavors is `Sender`.

## 2. Concrete message types

This chapter defines two **core** concrete messages — the framework-wide
property-change and lifecycle-transition signals — that ship in every VMx
binary regardless of opt-in features. Both are immutable. Additional
domain-specific messages introduced in later spec versions
(`TreeStructureChangedMessage` per chapter 18, `FormRevertedMessage` per
chapter 20, and `CollectionChangedMessage` per chapter 21) follow the
same `IMessage` contract documented here and are specified in their
respective chapters.

### 2.1 `PropertyChangedMessage<TSender>`

Emitted when a property's setter assigns a new value (a value not equal to the
existing one). Carries:

```
PropertyChangedMessage<TSender> : IMessage<TSender>:
    PropertyName : string
```

A factory `Create(sender, senderName, propertyName)` exists per language.

The `PropertyName` payload follows the emitting flavor's naming idiom per
ADR-0006 — `"IsValid"` (C#), `"is_valid"` (Python), `"isValid"` (TypeScript /
Swift). Subscribers filter with the idiomatic string of the flavor they are
written in (clarified in v2.5.0 via ADR-0037 after the TS and Swift flavors
were found emitting mixed casings).

### 2.2 `ConstructionStatusChangedMessage`

Emitted on every legal `Status` transition (see `02-lifecycle.md`). Carries:

```
ConstructionStatusChangedMessage : IMessage:
    Status : ConstructionStatus
```

A factory `Create(sender, senderName, status)` exists per language.

## 3. The hub contract

`IMessageHub` exposes:

```
IMessageHub:
    Messages : IObservable<IMessage>
    Send<TMessage : IMessage>(message: TMessage) : void

ITransactionalMessageHub : IMessageHub:
    Batch(transaction) : void
```

### 3.1 Hot stream semantics

The hub is a **hot** Rx stream:

- `Send` delivers to every current subscriber synchronously.
- A subscriber added after a `Send` call does NOT observe that message.
- There is no replay buffer.

### 3.2 Ordering

For a single producer (a single thread calling `Send` in sequence), every subscriber
observes the messages in send order (FIFO). Across producers (concurrent `Send`
calls), the hub MAY interleave but MUST preserve per-producer order: if producer P
sends `A` then `B`, no subscriber observes `B` before `A`.

### 3.3 Hub transactions and re-entrant delivery

A hub transaction is a synchronous scope that defers publication until its
outermost scope exits. It is exposed idiomatically in each flavor:

| Flavor     | API                             |
| ---------- | ------------------------------- |
| C#         | `hub.Batch(Action transaction)` |
| Python     | `with hub.batch(): ...`         |
| TypeScript | `hub.batch(() => { ... })`      |
| Swift      | `try hub.batch { ... }`         |
| Rust       | `hub.batch(closure)`            |

The transaction member is an additive capability (`ITransactionalMessageHub` /
`TransactionalMessageHubProto` / `ITransactionalMessageHub` /
`TransactionalMessageHubProtocol` as applicable), so adding it does not break
custom implementations of the established base hub contract. Every shipped
real and null hub implements the capability.

The contract is **lossless deferral**, not message coalescing:

1. Every `Send` inside a transaction appends its message to a hub-wide FIFO
   queue. No message is merged, replaced, or dropped.
1. Nested transactions flatten. Only exit from the outermost scope starts
   delivery.
1. Each queued message is delivered exactly once, in queue order, after the
   outermost scope exits.
1. If the transaction body raises, already-queued messages are still drained
   before the original error is rethrown. The body error takes precedence over
   a diagnostic raised while draining.
1. A subscriber MAY call `Send`. That message appends to the same queue and is
   delivered by the current iterative drain after the in-flight message has
   reached its current subscribers. Delivery MUST NOT recurse on the call
   stack.
1. Disposing the hub during a transaction completes the stream and drops the
   undelivered queue. Subsequent sends remain no-ops.

Outside a transaction, an ordinary top-level `Send` remains hot and
synchronous: it drains its message (and any finite re-entrant descendants)
before returning. A re-entrant `Send` itself returns after enqueueing; the
outermost `Send` does not return until the shared queue is empty.

Development builds MUST bound a single drain cycle and emit a loud overflow
diagnostic that names the message types involved. This is a cycle detector,
not a production limit: optimized/release configurations MUST disable or
compile out the bound and continue the correctness-preserving iterative drain
without dropping a finite message sequence. The Swift flavor reports through its development
diagnostic hook because its established `send` surface is non-throwing; the
other flavors raise/panic idiomatically.

TypeScript enables the bound automatically in Node development/test processes.
Browser hosts opt in with
`new MessageHub({ developmentDiagnostics: true })` because the web platform
has no standard development-mode flag; the browser default is unbounded so a
production bundle cannot accidentally truncate a valid finite transaction.

### 3.4 Subscriber resilience

If a subscriber's handler raises, the hub MUST swallow the exception (the stream
continues for other subscribers and for future `Send` calls). Raising subscribers
are a contributor concern, not a hub concern.

If a subscriber disposes its subscription during the delivery of a message (e.g.,
the handler calls `subscription.Dispose()`), the in-flight dispatch of *that* message
completes normally for the subscriber; subsequent messages are not delivered to that
subscriber. Other subscribers are unaffected.

### 3.5 Multiplicity

A host application MAY create as many `IMessageHub` instances as it likes. The
common pattern is one hub per VM tree (per "screen" or "feature"); shared root hubs
across the whole app are also valid.

## 4. Threading

`Send` runs on the calling thread. Subscribers wishing to observe on a specific
thread/scheduler MUST apply `.ObserveOn(scheduler)` themselves. VMx does not impose
a scheduler choice on the hub.

The real hubs serialize a transaction and its drain. A producer on another
thread that calls `Send` while a transaction or drain is active waits, then
performs synchronous delivery on its own calling thread. This retains the
per-producer FIFO and calling-thread guarantees. A transaction body therefore
MUST NOT wait for another thread whose progress requires sending to that same
hub. TypeScript has no shared-memory hub across workers; JavaScript jobs using
one hub are already serialized by the host event loop.

VMs that emit `PropertyChangedMessage` (Status changes, model changes, etc.) MAY
dispatch the emission via `IDispatcher.Foreground` so subscribers can opt into
foreground-thread delivery via `ObserveOn(dispatcher.Foreground)`. See
`11-threading.md` for the full contract.

## 5. Fixture

`fixtures/message-ordering.json` encodes the four scenarios that the `HUB-NNN`
conformance tests load:

- `single-producer-fifo`: 3 messages → 3 observations, same order.
- `late-subscribe-no-replay`: pre-subscribe sends are not observed.
- `multiple-subscribers-same-message`: every subscriber observes every post-subscribe
  message.
- `unsubscribe-during-emit`: a subscriber disposing during delivery does not crash.

## 6. Null variant — `NullMessageHub` (spec v2.0)

Every service contract in VMx has a **null-object** variant per ADR-0017. For
`IMessageHub`, the variant is `NullMessageHub`:

- `Send<TMessage>(message)` is a no-op. Calling it has no effect, raises
  nothing, returns immediately.
- The transaction API executes its body immediately and propagates its error,
  while all sends made through the null hub remain no-ops.
- `Messages` returns the empty observable (`Observable.Empty<IMessage>()` in
  C#, `reactivex.empty()` in Python, `EMPTY` in TypeScript,
  `Empty<...>(completeImmediately: true).eraseToAnyPublisher()` in Swift).
  It completes immediately upon subscription and emits no values.

`NullMessageHub` is safe to share across consumers; it holds no state. Typical
uses: a default for a VM whose hub is genuinely irrelevant; a placeholder in
tests; a stand-in when the hub injection chain is being torn down.

The null variant is conformance-tested by `NULL-001`.

## 7. Convenience helpers (informative)

Each flavor ships two small helpers over the hub for the single most common cross-VM
subscription pattern — observing one property of one *specific* sender. Both are
**informative**: neither carries a conformance ID, because the underlying `Messages`
stream (§3) is the conformance-tested contract (ADR-0032). They differ only in what
they emit — the property *value* versus the matching *message*.

### 7.1 `PropertyValueChangedMessagesFor` — project the value (spec v2.1)

Instead of filtering the full message stream and projecting the property value
manually, this helper returns `IObservable<TProperty>` (or equivalent) directly by:

1. Filtering `Messages` to `PropertyChangedMessage` instances whose sender is
   reference-equal to the given object and whose `PropertyName` matches.
1. Snapshotting the current property value from the sender at delivery time.

Per-flavor names and shapes:

| Flavor     | Name                                  | Entry point                             |
| ---------- | ------------------------------------- | --------------------------------------- |
| C#         | `PropertyValueChangedMessagesFor`     | Extension method on `IMessageHub`       |
| Python     | `property_value_changed_messages_for` | Module-level function in `vmx.messages` |
| TypeScript | `propertyValueChangedMessagesFor`     | Named export from `src/messages`        |
| Swift      | `propertyValueChangedMessagesFor`     | Method on `MessageHubProtocol`          |

See ADR-0032 for the rationale and full per-flavor signature table.

### 7.2 `whenPropertyChanged` — observe the message (spec v3)

`whenPropertyChanged(hub, sender, propertyName)` is the **canonical typed primitive
for a cross-VM subscription**. It returns the stream of `PropertyChangedMessage`
events published to `hub` by a *specific* `sender` for a *specific* property,
replacing the hand-wired filter —
`Messages.OfType<PropertyChangedMessage<…>>().Where(m => ReferenceEquals(m.SenderObject, sender) && m.PropertyName == p)`
— that flagship apps otherwise copy-paste into every binding (VMX-017). The helper:

1. Filters `Messages` to `PropertyChangedMessage` instances whose runtime sender is
   reference-equal (identity) to `sender` and whose `PropertyName` equals
   `propertyName` by exact string match (idiomatic-cased per ADR-0006 — the
   subscriber passes the property name in its own flavor's idiom).
1. Emits the matching **message** itself (not the projected value), so the subscriber
   may read whatever state it needs from the sender at delivery time. Prefer §7.1
   when only the property value is wanted.

The C# helper matches across the covariant `IPropertyChangedMessage<TSender>`, so a
message published under any concrete sender generic argument is captured; sender
identity is always compared by reference, never by value. Null arguments raise.

Per-flavor names and shapes:

| Flavor     | Name                    | Entry point                             |
| ---------- | ----------------------- | --------------------------------------- |
| C#         | `WhenPropertyChanged`   | Extension method on `IMessageHub`       |
| Python     | `when_property_changed` | Module-level function in `vmx.messages` |
| TypeScript | `whenPropertyChanged`   | Named export from `src/messages`        |
| Swift      | `whenPropertyChanged`   | Method on `MessageHubProtocol`          |

Like §7.1 the helper is informative (no conformance ID); each full-parity flavor
covers it with a unit test (`WhenPropertyChangedTests` /
`test_when_property_changed` / `whenPropertyChanged.test.ts` / `PropertyChangedTests`
in Swift). See ADR-0050 for the rationale.

### 7.3 TypeScript raw-message predicates (informative, spec v3.14)

TypeScript additionally exports `isPropertyChanged`, `isCollectionChanged`,
and `isConstructionStatusChanged` for narrowing mixed raw `IMessage` arrays or
streams to the corresponding existing concrete message classes. Optional
constraint objects select the existing sender/source and family-specific fields;
the unary forms can be passed directly to `Array.filter` or RxJS `filter`.
Generic sender narrowing requires a supplied sender that is checked by identity;
generic collection-item narrowing requires a typed
`ServicedObservableCollection<TItem>` source. Property-only, action-only, and
opaque-source constraints retain `unknown`. Constraint fields use own-property
presence, so an explicitly supplied `undefined` value is compared exactly while
an omitted field is ignored.

These predicates classify existing message objects without changing message
semantics, delivery, ordering, lifecycle, or payloads. They are TypeScript-only
type ergonomics under ADR-0006, add no conformance ID, and create no API
requirement for the other flavors. Existing §7.1 and §7.2 helpers remain the
higher-level choices when the hub, sender, and property are already known. See
ADR-0094 for the exact matching and overload decisions.

## 8. Conformance

`HUB-001` through `HUB-013`, `PROP-001` through `PROP-004`, and the null-object
IDs `NULL-001` (NullMessageHub is a safe no-op) and `NULL-003` (paired null
variants exist for the core service contracts) in `12-conformance.md` cover:

- `Send` delivers to current subscribers synchronously
- late subscribers do not see prior messages (no replay)
- single-producer FIFO order
- subscriber disposing during emit does not crash the hub
- multiple subscribers each observe every post-subscribe message
- table-driven scenarios from `fixtures/message-ordering.json`
- subscriber handler raising does not break the hub
- nested transaction deferral and lossless FIFO delivery
- transaction-body errors drain queued messages before rethrowing
- iterative re-entrant publishing without recursive stack growth
- subscriber-failure isolation during a transaction drain
- disposal during a transaction drops the pending queue
- unchanged synchronous semantics for ordinary non-batch sends
- `PropertyChangedMessage` emitted on real changes only (not on same-value sets)
- sender identity / property name / sender name correctness
