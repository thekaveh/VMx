# ADR 0095 — Add a cross-flavor selected-state subscription bridge

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.15.0
**Related:** ADR-0002, ADR-0006, ADR-0032, ADR-0050, ADR-0082, issue #93, issue #136

## 1. Context

Imperative consumers such as renderers, audio engines, canvas hosts, and shader
uniform bridges need selected VM state without a UI render loop. Existing
property-message filters and property-specific value streams do not own the
whole selector lifecycle: initial snapshot, equality, current/previous callback
values, and deterministic teardown.

The motivating use cases observe one fixed VM. Dynamic collection-member
discovery and resubscription have different lifetime and fan-in semantics and
remain issue #136.

## 2. Decision

1. Add one language-neutral `subscribeValue` concept. It subscribes to the
   source VM's injected message hub, accepts only property messages from that
   fixed source, evaluates a selector, and invokes an imperative callback with
   `(current, previous)`. C#, Python, TypeScript, and Swift match the runtime
   source by object identity. Rust expresses the same boundary as a hub plus
   `sender_id` and matches the property message's sender ID.

1. Expose the concept idiomatically in each flavor:

   | Flavor     | Shape                                                                                                           |
   | ---------- | --------------------------------------------------------------------------------------------------------------- |
   | C#         | `source.SubscribeValue(selector, callback, equalityComparer?, fireImmediately?)`                                |
   | Python     | `subscribe_value(source, selector, callback, *, equality=None, fire_immediately=False)`                         |
   | TypeScript | `subscribeValue(source, selector, callback, { equality?, fireImmediately? })`                                   |
   | Swift      | `subscribeValue(source, selector:, callback:, isEqual:, fireImmediately:)` plus an `Equatable` default overload |
   | Rust       | `hub.subscribe_value(sender_id, selector, callback, options)` with a default-`PartialEq` convenience shape      |

   Every flavor returns its established subscription or disposable type and
   adds no reactive dependency.

1. Setup is synchronous and ordered: validate arguments where idiomatic,
   evaluate the selector exactly once, optionally call
   `callback(initial, initial)`, set the retained current baseline, then attach
   the hub subscription. The immediate callback deliberately runs before
   attachment. A mutation it performs is not replayed, and setup is not an
   atomic transaction with unrelated concurrent producers.

1. For each matching property message, evaluate the selector once into `next`
   and equality once as `(current, next)`. An equal result ends that delivery.
   Otherwise retain the old value as `previous`, update the current baseline to
   `next`, and only then call `callback(next, previous)`. Updating first ensures
   a re-entrant source change compares against the newest baseline when the
   hub's iterative FIFO drain reaches it.

1. Default equality follows the flavor's normal value equality:

   | Flavor     | Default equality                     |
   | ---------- | ------------------------------------ |
   | C#         | `EqualityComparer<TValue>.Default`   |
   | Python     | `==`                                 |
   | TypeScript | `Object.is`                          |
   | Swift      | `==` on the `Equatable` overload     |
   | Rust       | `PartialEq` on the convenience shape |

   Every flavor supports custom equality. Swift and Rust custom-comparator
   shapes do not require the default equality constraint. A comparator is
   evaluated once per matching message.

1. Initial-selector and immediate-callback failures propagate synchronously and
   attach no subscription. Delivery-time selector, equality, and callback
   failures use the flavor's existing HUB-007 subscriber-error route and cannot
   break the hub or another subscriber. Because the baseline changes before a
   delivery callback, callback failure does not roll it back. Swift throwing
   selectors and callbacks are isolated by `MessageHubProtocol.subscribe`,
   Rust panics are isolated by the hub, and the other flavors retain their
   existing observer boundaries.

1. The returned handle owns teardown. Disposal is idempotent according to the
   established handle type; no later message invokes the selector, equality, or
   callback. Disposal during a callback does not abort that callback, but it
   prevents subsequent queued or re-entrant messages from reaching the
   subscription. The helper is not automatically registered as a resource of
   the observed VM because the imperative consumer owns the bridge lifetime.

1. Hub batches remain lossless. The helper examines each delivered matching
   property message, but the selector reads current state at delivery time. If
   several queued messages all observe the same final selected value, equality
   naturally reduces them to one callback; the helper does not coalesce hub
   messages.

1. This is strictly a fixed-source bridge. It performs no dependency tracking,
   dynamic collection-member fan-in, or automatic resubscription; those remain
   issue #136.

## 3. Consequences

- Imperative consumers receive deterministic initial, current/previous,
  equality, failure, re-entrancy, and teardown behavior without rebuilding it
  around raw message filters.
- Explicit modeled-component republishes are visible because the selector runs
  for every matching property message even when the selected value later
  equality-suppresses the callback.
- `whenPropertyChanged`, `propertyValueChangedMessagesFor`, and TypeScript's raw
  message predicates retain their existing behavior and preferred use cases.
- The implementation change will add `SUBV-001` through `SUBV-004` to all five
  full-parity suites and the conformance catalog. The 3.15.0 version, package,
  compatibility, changelog, count, and documentation-surface updates land with
  those implementations rather than in this decision-only change.

## 4. Rejected alternatives

- **Subscribe to the VM-local property stream:** the local channel does not have
  uniform subscriber-failure behavior across flavors; notably, a C# event
  handler can escape the source setter. Reimplementing isolation there would
  duplicate the established hub contract.
- **Expose only an Observable/Publisher factory:** a reactive stream would leave
  initial delivery, current/previous state, callback ownership, and cleanup in
  every imperative consumer. The required bridge owns those concerns.
- **Observe dynamic collection members:** this would conflate one fixed sender
  with discovery, removal, and per-member lifetime rules reserved for issue
  #136.
