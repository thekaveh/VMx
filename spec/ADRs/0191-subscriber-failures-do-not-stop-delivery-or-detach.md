# ADR 0191 — Subscriber failures do not stop delivery or detach a subscription

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §3.4 and §3.6, chapter 01 §1.4,
  chapter 04 §4, chapter 06 §8.2, chapter 15 §4.1, chapter 21 §2.5, `HUB-007`,
  `CMD-021`, `SRCH-009`, `DPROP-013` and `COL-069`)
- **Extends:** [ADR-0171](0171-failing-local-subscriber-does-not-suppress-the-hub-message.md).
  Related: [ADR-0011](0011-derived-properties.md),
  [ADR-0014](0014-search-and-filter.md),
  [ADR-0095](0095-cross-flavor-subscribe-value.md), #374, #1304,
  #1311.

## 1. Context

Chapter 03 §3.4 (`HUB-007`) is the only rule for a failing subscriber. The hub
swallows the failure, and the stream continues. No rule covered the other
library channels, and the flavors differ.

**Derived streams (#1304).** A C# probe on .NET 10 at `349ca128` gave these
results:

- `DerivedProperty`: a `ValueChanged` subscriber throws on the first change.
  The source emission rethrows, and `Value` then stops updating. Rx's
  safeguard disposes the property's own `Select` subscription, and
  `AsObservable()` disposes the consumer.
- `SearchableState`: a predicate throws for one term. After a valid term,
  `Filtered` keeps the unfiltered list. The recompute subscription is gone.
- Hub helpers: a `PropertyValueChangedMessagesFor` subscriber that throws on
  every message receives 1 of 2 messages. A raw `hub.Messages` subscriber
  receives 2 of 2. The isolating observer wraps the first operator of the
  helper's chain, and Rx disposes the chain first.
- `RelayCommand`: a `CanExecuteChanged` handler throws once. A raw `Subject`
  trigger raises the event again. A trigger built with `Select` does not.

Python lets the failure reach the publisher, and the subscription stays.
TypeScript reports it through rxjs, and the subscription stays. Rust catches
the panic for each subscriber. Swift subscribers and predicates cannot fail.

**Local fan-out (#1311).** ADR-0171 keeps the hub message when a local
subscriber fails. It gave no rule for the later local subscribers. C# raises
each local event as one multicast delegate call, and Python delivers through
one reactivex `Subject.on_next` call. Both stop at the first failing
subscriber, so the later subscribers miss the change. Python completion at
dispose stops in the same way. rxjs 7 and the Rust `MessageHub` deliver to
every subscriber.

## 2. Decision

### 2.1. Owner decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen. Four of the five flavors already
deliver to every subscriber and keep each subscription. C# and Python move to
that behavior.

### 2.2. Channels

The rules apply to these library channels:

1. The hub `Messages` stream and the chapter 03 §7.1 and §7.2 helpers.
1. `DerivedProperty.ValueChanged` and the property's own source subscription.
1. `SearchableState.Filtered`, the predicate and item supplier of a recompute,
   and the helper's own recompute subscription.
1. Command `CanExecuteChanged` and the command's trigger subscriptions. The
   decorators and the composite command forward the event under the same rule.
1. The local collection-change channel of the hub-publishing collections, the
   dictionary's granular events, and the local `CollectionChanged` channel of
   `CompositeVM` and `GroupVM`, including its completion at disposal.

Only these deliveries are *call-fed*: a mutation or disposal on channel 5, the
disposal of a `DerivedProperty` or `SearchableState`, and a
`RaiseCanExecuteChanged` call. Every other delivery is *stream-fed*. This
includes a hub `Send`, a trigger emission, a `SearchableState` term change and
a `search()` call. A closed list keeps the route clear when a caller's method
call starts a stream-fed delivery.

### 2.3. Rules

Chapter 03 §3.6 states these rules.

1. **Every subscriber.** A delivery reaches each subscriber that is attached
   when it starts, once, even when an earlier subscriber fails. Completion
   follows the same rule.
1. **No detach.** A failure does not detach the failing subscriber, another
   subscriber or the library's own source subscription. Later deliveries reach
   all of them.
1. **State first.** The library commits the state that a delivery announces
   before it delivers. A failure does not roll that state back.
1. **Stream-fed route.** A failure never reaches the upstream publisher. Each
   flavor reports it through its `HUB-007` route (table in §2.4).
1. **Call-fed route.** C# and Python rethrow the first failure to the caller
   after the delivery and any hub send, as ADR-0171 states. TypeScript, Swift
   and Rust follow the stream-fed route and return normally.
1. **Failing recompute.** A `SearchableState` predicate or item supplier that
   fails during a recompute stops that recompute. `Filtered` keeps its last
   snapshot and emits nothing. The failure follows rule 4, and later
   recomputes run as usual. A failure in the constructor's first filter still
   reaches the constructor's caller.
1. **Consumer operators.** The rules cover a subscription made directly on a
   stream that the library returns. A subscription made through operators that
   the consumer adds follows the reactive library's own rules. In C#, Rx
   disposes such a subscription when its callback throws.

### 2.4. Stream-fed route per flavor

| Flavor     | Route                                                                                 |
| ---------- | ------------------------------------------------------------------------------------- |
| C#         | The failure is caught at the subscriber and discarded, as the hub does.               |
| Python     | The failure is caught at the subscriber and logged with `logger.exception`.           |
| TypeScript | rxjs reports the failure asynchronously through `config.onUnhandledError`.            |
| Swift      | Subscribers, predicates and triggers cannot fail; a hub handler's error is discarded. |
| Rust       | The panic is caught for each subscriber; the default panic hook reports it.           |

### 2.5. Out of scope

- A throwing transform or a failing source of a `DerivedProperty`. #374
  decides them. A consumer failure in this ADR never counts as a transform
  failure.
- `PropertyChanged` handlers and the dictionary key views. ADR-0171 keeps them
  out, and they need a redesign of the notification sequence.
- `AggregateChangeStream` subscriber failures. Chapter 21 §9.5 keeps the host
  convention. ADR-0192 fixes only its subscriber order.
- The order among the subscribers of one delivery. Only ADR-0192 fixes an
  order, for `AggregateChangeStream`.

## 3. Flavor impact

- **C#.** The library-returned streams stop using Rx operators at the
  subscriber boundary. `ValueChanged`, `Filtered` and the §7.1 and §7.2 helpers
  return VMx-owned observables that wrap each subscriber in an isolating
  observer, as `MessageHub.Messages` does. `SearchableState` catches a
  predicate or supplier failure in its recompute callback. Trigger callbacks
  catch the failure of `RaiseCanExecuteChanged`. Local events call each
  handler of the invocation list in turn and rethrow the first failure after
  the hub send.
- **Python.** A shared fan-out subject delivers to each observer in turn and
  re-raises the first failure. The collections, the dictionary, the containers
  and the commands use it for their local subjects. `value_changed`,
  `filtered` and the trigger callbacks isolate and log a failure.
  `SearchableState` catches and logs a predicate or supplier failure.
- **TypeScript.** No code change. rxjs already isolates each subscriber.
- **Swift.** No code change. Its subscribers cannot fail. Tests assert the
  structure.
- **Rust.** No code change. Its channels are `MessageHub` and `ValueStream`
  instances that catch each panic. `SearchableState` is pull-based (ADR-0099
  §2.7), so a panicking predicate reaches the caller of `filtered()`.

## 4. Conformance

- `HUB-007` now also requires that the failing subscriber stays attached and
  receives the second message.
- `DPROP-013` covers a failing `ValueChanged` subscriber.
- `SRCH-009` covers a failing predicate and a failing `Filtered` subscriber.
- `CMD-021` covers a failing `CanExecuteChanged` handler on the trigger path
  and on a direct raise.
- `COL-069` covers two local collection subscribers when the first fails.

The catalog grows from 451 to 456 library IDs (461 in total), together with
`AGCH-011` from ADR-0192.

## 5. Consequences

- One failing handler can no longer freeze a `DerivedProperty` or a
  `SearchableState` for every reader in C#.
- A C# or Python derived-stream failure no longer reaches the code that fed
  the source. Python logs it, and C# discards it, as their hubs do.
- In C# and Python, the later local subscribers of a collection or container
  receive each change, and every completion observer completes.
- C# and Python callers of a collection or container mutation still see the
  first local failure (ADR-0171).
- Open decision §1.2 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` now covers only
  the transform and source cases of #374.

## 6. Rejected alternatives

- **Let stream-fed failures reach the upstream publisher.** In C# the failure
  passes an Rx safeguard, which disposes the subscription. It also stops the
  upstream subject before its later subscribers. One consumer's bug would
  break another component.
- **Detach the failing subscriber.** One bad handler would silently freeze
  derived state for every reader. No flavor except C# does this.
- **Keep the C# and Python fan-out and record a divergence.** Applications
  would depend on handler order, and three flavors already deliver to every
  subscriber.
- **Swallow call-fed failures in C# and Python too.** ADR-0171 keeps the
  failure visible to the caller, and both flavors propagate subscriber
  failures to the caller elsewhere.
- **Isolate consumer-built operator chains.** The library cannot reach a
  subscription that the consumer builds on top of its streams.
