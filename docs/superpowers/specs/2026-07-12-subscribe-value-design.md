# `subscribeValue` design

**Issue:** #93\
**Status:** Approved by the ready-for-work issue contract and the continuous VMx queue\
**Target:** spec 3.15.0

## 1. Problem

Imperative consumers such as renderers, audio engines, canvas hosts, and shader
uniform bridges need selected VM state without involving a UI render loop. VMx
currently offers property-message filters and property-specific value streams,
but no helper owns the full selector lifecycle: initial snapshot, equality,
current/previous callback values, and deterministic teardown.

The new concept observes one fixed VM. It is not dynamic collection-member
fan-in; that remains issue #136.

## 2. Approaches considered

### 2.1 Fixed-source hub subscription — selected

Subscribe to the source VM's injected hub, accept only
`PropertyChangedMessage` events from that source, and evaluate an arbitrary
selector. This works for ordinary changes and explicit model republishes, uses
the existing lossless/re-entrant hub ordering, and inherits HUB-007 subscriber
failure isolation.

### 2.2 Local `propertyChanged` channel

The per-VM channel removes the sender filter, but its exception behavior is not
uniform: notably, a C# event handler can escape the source setter. Reimplementing
failure isolation around every local channel would duplicate the hub contract.

### 2.3 Observable/Publisher factory only

Returning another reactive stream is composable but leaves initial delivery,
current/previous state, callback ownership, and cleanup in consumer code. The
ticket specifically requires an imperative, no-render bridge.

## 3. Conceptual contract

The language-neutral shape is:

```text
subscribeValue(source, selector, callback, options?) -> teardown handle
```

- `source` is one fixed VM with an injected message hub. Rust expresses the
  same identity as `hub + sender_id` because Rust messages are intentionally
  ID-based.
- `selector` maps the source's current state to `TValue`.
- `callback` receives `(current, previous)`.
- options provide custom equality and `fireImmediately`.
- every flavor returns its established subscription/disposable type.

Per-flavor entry points are idiomatic:

| Flavor     | Shape                                                                                                           |
| ---------- | --------------------------------------------------------------------------------------------------------------- |
| C#         | `source.SubscribeValue(selector, callback, equalityComparer?, fireImmediately?)`                                |
| Python     | `subscribe_value(source, selector, callback, *, equality=None, fire_immediately=False)`                         |
| TypeScript | `subscribeValue(source, selector, callback, { equality?, fireImmediately? })`                                   |
| Swift      | `subscribeValue(source, selector:, callback:, isEqual:, fireImmediately:)` plus an `Equatable` default overload |
| Rust       | `hub.subscribe_value(sender_id, selector, callback, options)` with a default-`PartialEq` convenience shape      |

No flavor adds another reactive library.

## 4. State machine and ordering

Setup is synchronous:

1. Validate callable/source arguments where the language normally does so.
1. Evaluate `selector` exactly once and retain that initial value.
1. If `fireImmediately` is true, invoke `callback(initial, initial)`.
1. Attach the hub subscription and return its teardown handle.

The immediate callback deliberately precedes attachment. This avoids a nested
delivery during setup and matches the established subscribe-with-selector
convention. A mutation performed by the immediate callback is not replayed;
consumers should treat that callback as initial synchronization, not as a
mutation hook. Setup is not an atomic transaction with unrelated concurrent
producers.

For each matching property message:

1. Evaluate `selector` exactly once into `next`.
1. Evaluate equality exactly once as `(current, next)`.
1. If equal, do nothing.
1. Otherwise save `previous = current`, assign `current = next`, then invoke
   `callback(next, previous)`.

Updating the baseline before the callback is essential. If the callback changes
the source, the existing iterative hub drain delivers that re-entrant message
after the current callback and compares it with the newest baseline.

Messages from other senders and non-property message families never evaluate
the selector.

## 5. Equality

The default is each flavor's normal value equality:

- C#: `EqualityComparer<TValue>.Default`
- Python: `==`
- TypeScript: `Object.is`
- Swift: `==` for the default `Equatable` overload
- Rust: `PartialEq` for the default convenience shape

Swift and Rust also expose a custom-comparator shape that does not require the
default equality path. A custom comparator is called once per matching message.
Neither the default nor custom path evaluates the selector twice.

## 6. Disposal, batching, and errors

Disposing/cancelling/unsubscribing the returned handle is idempotent according
to the flavor's existing subscription type. No later message invokes selector,
equality, or callback. Disposal during a normal callback prevents subsequent
queued/re-entrant messages from reaching that subscription; it does not abort
the callback already running.

The helper does not auto-register itself as a VM-owned resource because the
imperative consumer, not necessarily the observed VM, owns the bridge lifetime.
Consumers may register or dispose the handle using their normal host lifecycle.

Hub batches remain lossless. The helper examines every delivered property
message, but selectors read current state at delivery time. If several queued
messages all observe the same final selected value, equality naturally reduces
them to one callback; this is not message coalescing.

Errors are split by phase:

- Initial selector or immediate-callback failure propagates synchronously and
  no subscription is attached.
- Delivery-time selector, equality, or callback failure follows the flavor's
  existing HUB-007 subscriber-error route. It cannot break the hub or another
  subscriber.
- The selected baseline changes before a delivery-time callback is invoked, so
  a callback failure does not roll the helper back to stale state.

Swift selectors/callbacks may throw and are isolated by
`MessageHubProtocol.subscribe`. Rust panics are isolated by the hub. Other
flavors use their existing observer boundaries.

## 7. Normative coverage

The feature is a cross-flavor behavioral contract rather than another
informative convenience alias. Add four conformance scenarios:

- `SUBV-001`: fixed-source filtering, initial/current/previous values, default
  equality, and optional immediate delivery.
- `SUBV-002`: custom equality and exactly one selector/equality evaluation per
  matching message.
- `SUBV-003`: re-entrant FIFO behavior, batch final-state suppression, and
  deterministic disposal including disposal during callback.
- `SUBV-004`: setup failure propagation and delivery-time subscriber failure
  isolation with the baseline retained.

Every full-parity flavor implements all four. The catalog becomes 346 library
IDs plus five `THEME` scenarios, 351 total.

## 8. Documentation and consumer pilot

Canonical documentation adds an imperative engine/uniform bridge:

```typescript
const sub = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);
```

The same source generates the `.io` site and GitHub wiki. Root and per-flavor
READMEs describe their entry points and teardown handles.

A disposable DayDreams clone migrates the fixed `manifest` and `state`
subscriptions in `subscribeOverlayReconcile` to two `subscribeValue` bridges.
The dynamic cell collection/member subscription remains unchanged because it is
#136's scope. The pilot records deleted raw message filtering/casts and verifies
unchanged renderer tests without modifying the user's real DayDreams checkout.

## 9. Release discipline

This behavior change adds ADR-0095, updates the messages chapter and conformance
catalog, and advances the spec/stable flavors to 3.15.0 (Rust 0.15.0). Update
the compatibility matrix, changelogs, count claims, and three documentation
surfaces in the same change.

## 10. Non-goals

- No React hook, render scheduler, polling loop, or frame clock.
- No dynamic collection-member discovery or resubscription.
- No dependency tracking inside selectors.
- No message coalescing or change to hub batching.
- No automatic ownership by the observed VM.
- No replacement or behavioral change to `whenPropertyChanged`,
  `propertyValueChangedMessagesFor`, or TypeScript raw-message predicates.
