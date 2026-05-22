# 03 — Messages and the message hub

VMx uses a single hot pub/sub stream — the message hub — to convey property changes,
lifecycle status changes, and any future event types. Subscribers observe via an Rx
`IObservable<IMessage>`.

## `IMessage` shape

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

## Concrete message types

VMx 1.0 defines two concrete messages. Both are immutable.

### `PropertyChangedMessage<TSender>`

Emitted when a property's setter assigns a new value (a value not equal to the
existing one). Carries:

```
PropertyChangedMessage<TSender> : IMessage<TSender>:
    PropertyName : string
```

A factory `Create(sender, senderName, propertyName)` exists per language.

### `ConstructionStatusChangedMessage`

Emitted on every legal `Status` transition (see `02-lifecycle.md`). Carries:

```
ConstructionStatusChangedMessage : IMessage:
    Status : ConstructionStatus
```

A factory `Create(sender, senderName, status)` exists per language.

## The hub contract

`IMessageHub` exposes:

```
IMessageHub:
    Messages : IObservable<IMessage>
    Send<TMessage : IMessage>(message: TMessage) : void
```

### Hot stream semantics

The hub is a **hot** Rx stream:

- `Send` delivers to every current subscriber synchronously.
- A subscriber added after a `Send` call does NOT observe that message.
- There is no replay buffer.

### Ordering

For a single producer (a single thread calling `Send` in sequence), every subscriber
observes the messages in send order (FIFO). Across producers (concurrent `Send`
calls), the hub MAY interleave but MUST preserve per-producer order: if producer P
sends `A` then `B`, no subscriber observes `B` before `A`.

### Subscriber resilience

If a subscriber's handler raises, the hub MUST swallow the exception (the stream
continues for other subscribers and for future `Send` calls). Raising subscribers
are a contributor concern, not a hub concern.

If a subscriber disposes its subscription during the delivery of a message (e.g.,
the handler calls `subscription.Dispose()`), the in-flight dispatch of *that* message
completes normally for the subscriber; subsequent messages are not delivered to that
subscriber. Other subscribers are unaffected.

### Multiplicity

A host application MAY create as many `IMessageHub` instances as it likes. The
common pattern is one hub per VM tree (per "screen" or "feature"); shared root hubs
across the whole app are also valid.

## Threading

`Send` runs on the calling thread. Subscribers wishing to observe on a specific
thread/scheduler MUST apply `.ObserveOn(scheduler)` themselves. VMx does not impose
a scheduler choice on the hub.

VMs that emit `PropertyChangedMessage` (Status changes, model changes, etc.) MAY
dispatch the emission via `IDispatcher.Foreground` so subscribers can opt into
foreground-thread delivery via `ObserveOn(dispatcher.Foreground)`. See
`11-threading.md` for the full contract.

## Fixture

`fixtures/message-ordering.json` encodes the four scenarios that the `HUB-NNN`
conformance tests load:

- `single-producer-fifo`: 3 messages → 3 observations, same order.
- `late-subscribe-no-replay`: pre-subscribe sends are not observed.
- `multiple-subscribers-same-message`: every subscriber observes every post-subscribe
  message.
- `unsubscribe-during-emit`: a subscriber disposing during delivery does not crash.

## Conformance

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
