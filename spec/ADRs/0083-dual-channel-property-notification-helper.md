# ADR 0083 — Add one dual-channel property notification helper

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.3.0

## 1. Context

VMx intentionally has two property-change audiences. A shared message hub
coordinates across a VM tree, while a per-instance property-change surface is
the efficient binding target for one view and one VM. Consumer subclasses have
had to publish both manually. NNx Studio contains repeated setters that assign
state, send `PropertyChangedMessage`, and separately raise `propertyChanged`;
omitting the second call caused a real stale-view defect.

The issue originally proposed a wrapped or decorated one-line reactive
property. ADR-0040 already rejected a first-class `IProperty` abstraction in
favor of ordinary host-language properties. The safety problem is duplicated
notification ritual, not storage or accessor syntax.

Rust joined as a fifth full-parity flavor after the four-flavor per-instance
surface was documented. Its component implementation published the shared hub
message but did not yet expose the corresponding VM-local property-name stream.

## 2. Decision

Add one idiomatic dual-channel notification helper to the component base shape:

- C#: `NotifyPropertyChanged`
- Python: `_notify_property_changed`
- TypeScript and Swift: `_notifyPropertyChanged`
- Rust: `notify_property_changed`

A caller first determines that a state or derived-value change was accepted;
setters perform equality comparison and assignment themselves. The helper then
invokes exactly one hub `PropertyChangedMessage` send followed by exactly one
VM-local property-name notification. Ordinary top-level hub delivery is
observed first. Transactions and re-entrant hub drains retain enqueue order but
may defer the hub observer until after the local observer, as defined by
ADR-0082. The helper preserves public property-name casing and emits nothing
when called after disposal. A call admitted before disposal completes both
channels even when a hub observer disposes the VM re-entrantly.

Existing local-only raise primitives remain source-compatible and remain the
right mechanism for lifecycle/computed notifications that are deliberately not
hub messages. Existing library and flagship-example sites that manually perform
both emissions migrate to the helper.

Rust gains an additive per-instance `PropertyChangedStream` and subscription
handle. This closes the four-to-five-flavor documentation gap and gives Rust
adapters the same local binding target without coupling core to a UI framework.

Conformance IDs CVM-007 through CVM-009 cover multiplicity/order/current-value
visibility, caller-owned equality gating, and post-dispose behavior.

## 3. Consequences

- Consumer setters still look and behave like ordinary language properties;
  the helper removes only the error-prone dual-emission ritual.
- The two channels remain distinct because they serve different subscription
  scopes. Adapters no longer need consumers to remember both calls.
- Hub-send-before-local invocation is normative; observed delivery follows the
  transaction/re-entrant queuing rules of ADR-0082.
- Direct use of the lower-level hub/local primitives remains possible for
  intentionally single-channel behavior, but subclass-authored settable
  properties should prefer the helper.
- The specification advances to 3.3.0. C#, Python, TypeScript, and Swift advance
  to 3.3.0; pre-1.0 Rust advances to 0.3.0.

## 4. Rejected alternatives

### 4.1 Add an `IProperty` wrapper, decorator, or implicit accessor

Rejected by ADR-0040 and still unnecessary. It would own storage and introduce
a second property idiom when only notification composition is missing.

### 4.2 Collapse the hub and local surfaces into one channel

Rejected. Tree-wide coordination and per-instance binding have different
filtering, ownership, and adapter costs. Removing either would be a breaking
change and would make one audience less efficient.

### 4.3 Let each consumer define its own helper

Rejected. That preserves inconsistent ordering, disposal behavior, casing, and
the exact missed-channel bug this decision is meant to eliminate.

### 4.4 Have the helper perform equality checks or assignments

Rejected. Value equality, derived-change detection, and storage are
property-specific and language-specific. Keeping them at the mutation or
refresh site preserves transparent host-language semantics and keeps the
helper single-purpose.
