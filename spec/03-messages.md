# 03 — Messages and the message hub

VMx uses a single hot pub/sub stream — the message hub — to convey property changes,
lifecycle status changes, and any future event types. In C#, Python, and
TypeScript, subscribers observe an Rx `IObservable<IMessage>`. Swift exposes a
Combine `AnyPublisher<any Message, Never>`, and Rust registers closures with
`MessageHub::subscribe` on its VMx-owned hot stream.

## 1. `IMessage` shape

Every message carries one sender identity and one diagnostic sender name. The
current public surfaces express that invariant as follows:

| Flavor     | Untyped message shape                                | Typed sender shape                             |
| ---------- | ---------------------------------------------------- | ---------------------------------------------- |
| C#         | `IMessage.SenderName`, `IMessage.SenderObject`       | `IMessage<TSender>.Sender`                     |
| Python     | `Message.sender_name`, `Message.sender_object`       | `TypedMessage.sender`                          |
| TypeScript | `IMessage.senderName`, `IMessage.sender` (`unknown`) | `ITypedMessage<TSender>.sender`                |
| Swift      | `Message.senderName`, `Message.senderObject`         | concrete typed messages expose `sender`        |
| Rust       | `sender_name`, `sender_id`                           | enum variants retain the same numeric identity |

The diagnostic name typically equals the sender VM's `Name`. In the four
object-sender flavors, typed messages expose the canonical runtime sender as
`Sender`/`sender`. TypeScript also exposes that canonical member on its untyped
base. C#, Python, and Swift retain their legacy untyped base aliases for source
compatibility; adding a canonical member to those established base interfaces
is deferred to a future major (ADR-0054, ADR-0121).

Rust deliberately carries the VM's stable numeric `sender_id` instead of an
owned or borrowed runtime object. Its enum-based messages are not generic over
the sender type, and identity filters compare `sender_id`. This preserves the
same conceptual sender-identity contract without coupling a hot stream to
object ownership or lifetimes (ADR-0009, ADR-0120).

TypeScript exposes `sender` as its sole sender field as of v3.0.0, having
removed an earlier redundant untyped alias (ADR-0054). C#, Python, and Swift
retain the untyped base members shown in the table until their next major.
Concrete typed messages carry the same runtime instance through their canonical
`Sender`/`sender` member; Rust uses `sender_id`.

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

C#, Python, and TypeScript ship a factory `Create(sender, senderName, propertyName)` (`create` in Python and TypeScript). Swift uses the initializer
`PropertyChangedMessage(sender:senderName:propertyName:)`. Rust uses a plain
struct with public `sender_id`, `sender_name`, and `property_name` fields,
wrapped in `Message::PropertyChanged`.

The `PropertyName` payload follows the emitting flavor's naming idiom per
ADR-0006 — `"IsValid"` (C#), `"is_valid"` (Python / Rust), `"isValid"`
(TypeScript / Swift). Subscribers filter with the idiomatic string of the flavor they are
written in (clarified in v2.5.0 via ADR-0037 after the TS and Swift flavors
were found emitting mixed casings).

### 2.2 `ConstructionStatusChangedMessage`

Emitted on every legal `Status` transition (see `02-lifecycle.md`). Carries:

```
ConstructionStatusChangedMessage : IMessage:
    Status : ConstructionStatus
```

C#, Python, and TypeScript ship a factory `Create(sender, senderName, status)`
(`create` in Python and TypeScript). Swift uses the initializer
`ConstructionStatusChangedMessage(sender:senderName:status:)`. Rust uses a
plain struct with public `sender_id`, `sender_name`, and `status` fields,
wrapped in `Message::ConstructionStatusChanged`.

## 3. The hub contract

`IMessageHub` exposes:

```
IMessageHub:
    Messages : IObservable<IMessage>   # Swift: Combine publisher; Rust: subscribe(closure)
    Send<TMessage : IMessage>(message: TMessage) : void

ITransactionalMessageHub : IMessageHub:
    Batch(transaction) : void
```

### 3.1 Hot stream semantics

The hub is a **hot** stream (Rx in C#, Python, and TypeScript; Combine in
Swift; the VMx-owned stream in Rust):

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
   undelivered queue. Subsequent sends remain no-ops. A `Batch` on a disposed
   hub, or on a hub whose disposal is requested, runs its body. The body holds
   no scope that another call waits for (ADR-0184).

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
thread/scheduler MUST apply `.ObserveOn(scheduler)` themselves (Swift:
`receive(on:)`; Rust: hand the work to a `Dispatcher` from the subscriber
closure). VMx does not impose
a scheduler choice on the hub.

The real hubs serialize a transaction and its drain. A producer on another
thread that calls `Send` while a transaction or drain is active waits, then
performs synchronous delivery on its own calling thread. This retains the
per-producer FIFO and calling-thread guarantees, including when the producer is
already inside an unrelated hub callback.

Shared-memory flavors MUST track the wait-for relationship between a producer
thread and a foreign hub's batch/drain owner. Only when another wait would close
a real dependency cycle may the operation avoid waiting: a send enqueues for
the active owner drain, and disposal records terminal intent for that owner to
finish. A cyclic cross-hub batch uses a borrowed scope: its body may enqueue,
but the target owner does not resume draining until the borrowed scope exits.
Normal and unrelated nested batches retain exclusive ownership. This narrow
cycle escape preserves liveness without weakening ordinary `HUB-013`
synchronous delivery (ADR-0119). The hub records these waits in the flavor's
single wait-for graph (§4.1), and an open borrowed scope is itself a wait-for
owner (§4.2). TypeScript has no shared-memory hub across workers; JavaScript
jobs using one hub are already serialized by the host event loop.

VMs that emit `PropertyChangedMessage` (Status changes, model changes, etc.) MAY
dispatch the emission via `IDispatcher.Foreground` so subscribers can opt into
foreground-thread delivery via `ObserveOn(dispatcher.Foreground)`. See
`11-threading.md` for the full contract.

### 4.1 One wait-for graph per flavor (spec v3.30)

Each threaded flavor (C#, Python, Swift, and Rust) records every blocking wait
between VMx-owned resources in one process-wide wait-for graph (ADR-0172).
TypeScript is single-threaded and keeps no graph. The graph records these
waits. When a wait is refused, the operation takes the result in the last
column instead of blocking.

| Wait                                                                                    | Owner of the resource                        | Result of a refused wait                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A hub `Send`, `Batch`, or `Dispose` waits for the hub's batch, drain, or borrowed scope | The batch owner, the drainer, or a borrower  | `Send` enqueues for the active drain, `Batch` enters a borrowed scope, and `Dispose` records terminal intent for the owner (§4, ADR-0119)                                                                        |
| A hub drainer with queued messages waits for a borrowed scope                           | A borrower                                   | The drainer releases the drain to the borrowed scope's exit (§4.2)                                                                                                                                               |
| A foreign lifecycle call waits for one lifecycle delivery                               | The thread that drains the VM's publications | The call enqueues and returns to that drainer (chapter 02 §2.4, ADR-0117)                                                                                                                                        |
| A foreign `dispose()` waits for an admitted hook (its hook lease)                       | The thread that runs the hook                | Terminal cleanup is deferred to the hook's completion (chapter 02 §2.4, ADR-0126)                                                                                                                                |
| A cross-thread container disposal waits for a membership transaction                    | The transaction owner                        | Deferred terminal intent that the owner finishes (chapter 06 §4.2, ADR-0153)                                                                                                                                     |
| A structural operation waits for a child's ownership gate or lock                       | The thread whose transaction holds it        | The operation fails before mutation: `InvalidOperationException` in C#, `RuntimeError` in Python, and the container's attachment failure in Swift. Rust claims ownership without waiting, so it has no such wait |
| A `FormVM` call, settlement, or `Dispose()` waits for a form publication scope          | A thread that holds a scope on that form     | `SetModel` and deny are queued for the publisher, an approve call is admitted, a settlement opens its own scope, and `Dispose()` leaves the teardown to the publisher (chapter 20 §5.5, ADR-0176)                |

1. **One graph.** A wait that would close a cycle across any mix of these
   waits is refused. A wait that closes no cycle blocks as before. No flavor
   keeps a second graph for one family of waits. A Rust status publication is
   a hub send, so the hub row covers it.
1. **Edges per resource instance.** An edge names the waiting thread, the
   resource instance it waits for, and the thread that owns that resource. The
   resource instance is one hub, one lifecycle delivery, one hook lease, one
   container's membership transaction, one ownership gate or lock object, or
   one form's publication scope.
   An edge is never keyed by VM identity: a container that is also a child has
   a membership transaction and an ownership gate, and they are two resources.
   A waiting thread has at most one edge. A wait with several possible owners
   names one: the batch owner, then the drainer, then a borrower other than
   the caller.
1. **Live cycles only.** A cycle counts only when every owner on it still holds
   its resource at the time of the check. The check and the new edge are one
   atomic step under the graph's own lock. That lock is a leaf: a thread that
   holds it takes no other lock and runs no consumer code.
1. **Release before wake.** The thread that ends a wait removes the edges, and
   the ownership records, that name it as the owner of that resource before it
   wakes the waiters. This applies when a thread finishes a hook, delivers a
   publication, ends a membership transaction, releases an ownership gate,
   ends a batch, releases a drain, closes its outermost form publication
   scope, and when a borrower ends or partially exits its borrowed scopes. A
   woken waiter that must still wait records its wait
   again. A stale edge never makes an operation take its refused-wait result,
   and a released owner never keeps a waiter blocked.

### 4.2 Borrowed batch scopes (spec v3.30)

A borrowed scope (§4) is open from the start of a cyclic batch's body to its
exit. These rules apply in every threaded flavor (ADR-0172).

1. **A wait-for owner.** A thread with an open borrowed scope owns the hub
   with the batch owner and the drainer. A wait on the hub for a borrowed scope
   records an edge to a borrower (§4.1). When a borrower exits its last
   borrowed scope while other borrowers remain, the waiters wake.
1. **Empty queue.** A drainer whose queue is empty does not wait for a
   borrowed scope. It releases the drain and returns. The exit of the last
   borrowed scope drains what the bodies enqueued. This is not an escape: the
   drainer's outermost `Send` returns with an empty queue (§3.3).
1. **Borrower calls.** A borrower's own `Send`, `Batch`, and `Dispose` on the
   hub it borrowed do not wait. `Send` enqueues for the drain at the borrowed
   scope's exit. `Batch` nests another borrowed scope while no disposal is
   requested. After a disposal is requested, the body runs with no new scope
   (§3.3, ADR-0184). `Dispose` records terminal intent. The last of the batch
   owner, the drainer, and the borrowers to release the hub finishes the
   disposal. A drainer stops waiting for borrowed scopes once a disposal is
   requested, so its wait never holds a disposal open. A drain that is still
   delivering a message when the other owners exit finishes the disposal at its
   end.
1. **No callback-context escape.** A wait does not change because the caller
   is inside a hub callback. A `Send` to a hub with an open borrowed scope
   waits for it, and enqueues without waiting only when its wait is refused
   (§4.1, `HUB-013`).
1. **A drainer with queued messages (limitation).** A drainer with queued
   messages waits until no borrowed scope is open. A borrower can already
   wait, directly or through other threads, for that drainer. Then the wait
   that closes the cycle is refused. When the borrower's wait closes it, the
   borrower takes the result of its own operation (§4.1). When the drainer's
   wait closes it, the drainer releases the drain and returns, with its
   messages still queued. The thread that exits the last borrowed scope
   delivers them in FIFO order before that exit returns. The observable result
   is as follows. The drainer's outermost `Send` or batch returns before those
   messages reach subscribers, and they are delivered on the borrower's
   thread. This is the one case where an outermost `Send` returns with a
   non-empty queue (§3.3, `HUB-010`). Per-producer FIFO order (§3.2) still
   holds.

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
  It completes immediately upon subscription and emits no values. Rust
  `NullMessageHub::hub()` returns a new, already-disposed `MessageHub` on each
  call; sends to it are no-ops and it delivers nothing.

`NullMessageHub` is safe to share across consumers; it holds no state. Typical
uses: a default for a VM whose hub is genuinely irrelevant; a placeholder in
tests; a stand-in when the hub injection chain is being torn down.

The null variant is conformance-tested by `NULL-001`.

## 7. Subscription helpers

Each flavor ships two small helpers over the hub for the single most common cross-VM
subscription pattern — observing one property of one *specific* sender. Both are
**informative**: neither carries a conformance ID, because the underlying `Messages`
stream (§3) is the conformance-tested contract (ADR-0032). They differ only in what
they emit — the property *value* versus the matching *message*.

Sections 7.1–7.3 are informative convenience APIs. Section 7.4 defines the
normative cross-flavor `subscribeValue` behavior.

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

Rust ships no message-stream helper; consumers use `MessageHub::subscribe_value`
for a selected value, or `MessageHub::subscribe` with the
`Message::PropertyChanged` variant. See ADR-0032 for the rationale and full per-flavor signature table.

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

**Several names (spec v3.30, ADR-0160).** A multi-name form takes several
property names for the same `sender`, for example
`whenPropertyChanged(hub, chart, ["plot", "range"])`. It keeps the single-name
rules for sender identity, exact name match and flavor-idiom names. In
addition:

1. A message matches when its `PropertyName` equals any of the given names.
1. Each subscription to the result makes one subscription to `Messages`.
   Disposing that subscription stops every name.
1. Each matching message is emitted once, in hub order. A name that appears
   more than once in the list does not emit a message twice.
1. The names are copied when the helper is called. A later change to the
   caller's list has no effect.
1. At least one name is required. A call with none is rejected with the
   flavor's argument error, or it does not compile.
1. A single-name call behaves as before.

Per-flavor names and shapes:

| Flavor     | Name                    | Entry point                             | Multi-name form                                             | No names                       |
| ---------- | ----------------------- | --------------------------------------- | ----------------------------------------------------------- | ------------------------------ |
| C#         | `WhenPropertyChanged`   | Extension method on `IMessageHub`       | `params string[] propertyNames` overload                    | `ArgumentException`            |
| Python     | `when_property_changed` | Module-level function in `vmx.messages` | `property_name, *property_names` (pass `*names` for a list) | `TypeError` (missing argument) |
| TypeScript | `whenPropertyChanged`   | Named export from `src/messages`        | `propertyName: string \| readonly string[]`                 | `RangeError`                   |
| Swift      | `whenPropertyChanged`   | Method on `MessageHubProtocol`          | `String, String, String...` overload (two or more names)    | Does not compile               |

Like §7.1 the helper is informative (no conformance ID), and so is its multi-name
form; the four flavors that ship this convenience helper cover both with a unit
test (`WhenPropertyChangedTests` / `test_when_property_changed` /
`whenPropertyChanged.test.ts` / `PropertyChangedTests` in Swift). Rust consumers use `MessageHub::subscribe` with the
`Message::PropertyChanged` variant directly, for one name or several. See ADR-0050
for the rationale and ADR-0160 for the multi-name form.

### 7.3 TypeScript raw-message predicates (informative, spec v3.14)

TypeScript additionally exports `isPropertyChanged`, `isCollectionChanged`,
`isConstructionStatusChanged` and `isTreeStructureChanged` for narrowing mixed
raw `IMessage` arrays or streams to the corresponding existing concrete message
classes. `isTreeStructureChanged` classifies by class, then by shape, so a tree
message from a second copy of the package still matches. Optional
constraint objects select the existing sender/source and family-specific fields;
the unary forms can be passed directly to `Array.filter` or RxJS `filter`.
Generic sender narrowing requires a supplied sender that is checked by identity;
property-only constraints retain `unknown`. Collection predicates always narrow
payloads to `unknown`, because public message factories accept sender and item
types independently and source identity therefore cannot prove the payload
generic. Constraint fields use own-property presence, so an explicitly supplied
`undefined` value is compared exactly while an omitted field is ignored.

These predicates classify existing message objects without changing message
semantics, delivery, ordering, lifecycle, or payloads. They are TypeScript-only
type ergonomics under ADR-0006, add no conformance ID, and create no API
requirement for the other flavors. Existing §7.1 and §7.2 helpers remain the
higher-level choices when the hub, sender, and property are already known. See
ADR-0094 for the exact matching and overload decisions, and ADR-0163 for the
tree predicate.

### 7.4 `subscribeValue` — imperative selected-state bridge

`subscribeValue` observes selected state from one fixed VM and delivers it to an
imperative consumer without a render loop. The language-neutral shape is
`subscribeValue(source, selector, callback, options?) -> teardown handle`:

- `source` is one fixed VM with an injected message hub. Rust expresses the same
  identity as `hub + sender_id` because Rust messages are ID-based.
- `selector` maps the source's current state to `TValue`.
- `callback` receives `(current, previous)`.
- Options provide custom equality and `fireImmediately`.
- The result is the flavor's established subscription or disposable type.

The exact idiomatic entry points are:

| Flavor     | Shape                                                                                                           |
| ---------- | --------------------------------------------------------------------------------------------------------------- |
| C#         | `source.SubscribeValue(selector, callback, equalityComparer?, fireImmediately?)`                                |
| Python     | `subscribe_value(source, selector, callback, *, equality=None, fire_immediately=False)`                         |
| TypeScript | `subscribeValue(source, selector, callback, { equality?, fireImmediately? })`                                   |
| Swift      | `subscribeValue(source, selector:, callback:, isEqual:, fireImmediately:)` plus an `Equatable` default overload |
| Rust       | `hub.subscribe_value(sender_id, selector, callback, options)` with a default-`PartialEq` convenience shape      |

Setup and delivery follow this state machine exactly:

```text
initial = selector(source)
if fireImmediately: callback(initial, initial)
current = initial
on each property message from source:
    next = selector(source)
    if equality(current, next): stop this delivery
    previous = current
    current = next
    callback(current, previous)
```

Setup is synchronous. Arguments are validated where the flavor normally does
so, and the initial selector is evaluated exactly once. When requested, the
immediate callback runs before hub attachment. A mutation performed by that
callback is therefore not replayed; consumers treat it as initial
synchronization rather than a mutation hook. Setup is not an atomic transaction
with unrelated concurrent producers.

C#, Python, TypeScript, and Swift accept only `PropertyChangedMessage` events
whose sender is object-identical to `source`. Rust accepts only the property
message variant for which `message.sender_id == sender_id` on the supplied hub.
Messages from other senders and non-property message families do not evaluate
the selector.

Default equality is idiomatic:

| Flavor     | Default equality                     |
| ---------- | ------------------------------------ |
| C#         | `EqualityComparer<TValue>.Default`   |
| Python     | `==`                                 |
| TypeScript | `Object.is`                          |
| Swift      | `==` on the `Equatable` overload     |
| Rust       | `PartialEq` on the convenience shape |

Every flavor also accepts custom equality; Swift and Rust expose a
custom-comparator shape that does not require the default equality constraint.
The selector is evaluated at most once per matching message. Equality is
evaluated exactly once after the selector returns successfully, and zero times
if the selector fails.

An initial-selector or immediate-callback failure propagates synchronously and
no subscription is attached. A delivery-time selector, equality, or callback
failure follows the flavor's existing HUB-007 subscriber-error route and cannot
break the hub or another subscriber. The baseline is updated before a delivery
callback, so callback failure does not roll it back.

Swift selectors and callbacks may throw and are isolated by
`MessageHubProtocol.subscribe`; Rust panics are isolated by the hub. The other
flavors retain their existing observer boundaries.

Updating the baseline before invoking the callback also defines re-entrancy. If
the callback changes the source, the hub's existing iterative FIFO drain reaches
that message after the current callback and compares it with the newest
baseline. A batch remains lossless: the helper examines every delivered matching
property message, but the selector reads state at delivery time. When several
queued messages all observe the same final selected value, equality naturally
reduces them to one callback; this is not message coalescing.

Disposing, cancelling, or unsubscribing the returned handle is idempotent under
the flavor's established subscription contract. No later message invokes the
selector, equality, or callback. Disposal during a callback does not abort that
callback, but prevents subsequent queued or re-entrant messages from reaching
the subscription. The helper is not automatically registered as a resource of
the observed VM; the imperative consumer owns its lifetime.

The bridge does not perform dependency tracking, dynamic collection-member
fan-in, or automatic resubscription. Use `AggregateChangeStream` (ADR-0098) for
dynamic membership; see ADR-0095 for the fixed-source bridge.

## 8. Conformance

`HUB-001` through `HUB-013`, `PROP-001` through `PROP-004`, `SUBV-001` through
`SUBV-004`, and the null-object IDs `NULL-001` (NullMessageHub is a safe no-op)
and `NULL-003` (paired null variants exist for the core service contracts) in
`12-conformance.md` cover:

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
- fixed-source selected-state subscription with initial/current/previous values,
  optional immediate delivery, and default equality
- custom equality with exactly one selector/equality evaluation per matching
  property message
- re-entrant FIFO delivery, batch final-state suppression, and deterministic
  disposal including disposal during a callback
- synchronous setup failure propagation and delivery-time subscriber failure
  isolation with the selected baseline retained
