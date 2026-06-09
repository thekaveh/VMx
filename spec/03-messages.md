# 03 — Messages and the message hub

VMx uses a single hot pub/sub stream — the message hub — to convey property changes,
lifecycle status changes, and any future event types. Subscribers observe via an Rx
`IObservable<IMessage>`.

## 1. `IMessage` shape

Every message implements `IMessage` (rendered per language as `Message`):

```
IMessage:
    SenderName : string
    SenderObject : object
```

Strongly-typed senders are exposed via `IMessage<TSender>`:

```
IMessage<TSender> : IMessage:
    Sender : TSender
```

`SenderName` typically equals `Sender.Name`. `SenderObject` is the runtime sender
without compile-time type information (used by polymorphic subscribers).

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

### 3.3 Subscriber resilience

If a subscriber's handler raises, the hub MUST swallow the exception (the stream
continues for other subscribers and for future `Send` calls). Raising subscribers
are a contributor concern, not a hub concern.

If a subscriber disposes its subscription during the delivery of a message (e.g.,
the handler calls `subscription.Dispose()`), the in-flight dispatch of *that* message
completes normally for the subscriber; subsequent messages are not delivered to that
subscriber. Other subscribers are unaffected.

### 3.4 Multiplicity

A host application MAY create as many `IMessageHub` instances as it likes. The
common pattern is one hub per VM tree (per "screen" or "feature"); shared root hubs
across the whole app are also valid.

## 4. Threading

`Send` runs on the calling thread. Subscribers wishing to observe on a specific
thread/scheduler MUST apply `.ObserveOn(scheduler)` themselves. VMx does not impose
a scheduler choice on the hub.

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
- `Messages` returns the empty observable (`Observable.Empty<IMessage>()` in
  C#, `reactivex.empty()` in Python, `EMPTY` in TypeScript,
  `Empty<...>(completeImmediately: true).eraseToAnyPublisher()` in Swift).
  It completes immediately upon subscription and emits no values.

`NullMessageHub` is safe to share across consumers; it holds no state. Typical
uses: a default for a VM whose hub is genuinely irrelevant; a placeholder in
tests; a stand-in when the hub injection chain is being torn down.

The null variant is conformance-tested by `NULL-001`.

## 7. Convenience helpers (spec v2.1, informative)

Each flavor ships a small `PropertyValueChangedMessagesFor` (or per-flavor analog)
helper over the hub. Instead of filtering the full message stream and projecting the
property value manually, the helper returns `IObservable<TProperty>` (or equivalent)
directly by:

1. Filtering `Messages` to `PropertyChangedMessage` instances whose sender is
   reference-equal to the given object and whose `PropertyName` matches.
1. Snapshotting the current property value from the sender at delivery time.

Per-flavor names and shapes (all informative — no conformance IDs):

| Flavor     | Name                                  | Entry point                             |
| ---------- | ------------------------------------- | --------------------------------------- |
| C#         | `PropertyValueChangedMessagesFor`     | Extension method on `IMessageHub`       |
| Python     | `property_value_changed_messages_for` | Module-level function in `vmx.messages` |
| TypeScript | `propertyValueChangedMessagesFor`     | Named export from `src/messages`        |

See ADR-0032 for the rationale and full per-flavor signature table.

## 8. Conformance

`HUB-001` through `HUB-007` and `PROP-001` through `PROP-004` in `12-conformance.md` cover:

- `Send` delivers to current subscribers synchronously
- late subscribers do not see prior messages (no replay)
- single-producer FIFO order
- subscriber disposing during emit does not crash the hub
- multiple subscribers each observe every post-subscribe message
- table-driven scenarios from `fixtures/message-ordering.json`
- subscriber handler raising does not break the hub
- `PropertyChangedMessage` emitted on real changes only (not on same-value sets)
- sender identity / property name / sender name correctness
