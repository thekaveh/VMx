# ADR 0124 — Canonicalize forwarding ownership and callback boundaries

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Extends:** [ADR-0123](0123-preserve-container-causality-and-forwarding-ownership.md)

## 1. Context

ADR-0123 made a forwarding component a valid container child, but it did not
say how ownership behaves when the wrapped component already belongs to a
container or when more than one decorator references the same component. Some
flavors could consequently retain the wrapped identity in two containers.

The same audit exposed three transaction boundaries that needed explicit
language-neutral treatment: consumer current callbacks must not run under the
shared cross-composite coordinator; destination disposal after a successful
population hook must still reject and roll back admission; and replacement
rollback must restore the displaced child before a deferred destination
disposal takes its terminal snapshot.

## 2. Decision

- A component and every forwarding decorator around it share one canonical
  ownership identity. Attaching any one of those public identities transfers
  the canonical identity out of its previous composite or group first. The
  destination collection retains the exact decorator supplied by the caller;
  an older decorator is removed with its canonical wrapped identity.
- The shared cross-composite coordinator protects only validation and the
  committed current-state update, including affected child current flags. Hub
  publication and consumer callbacks run after that coordinator is released. A
  flavor may retain a lock-free logical
  transaction or use an equivalent current-publication lease; C# and Python
  close a standalone membership transaction first and use the lease, while a
  selection invoked from a structural callback reuses that callback's existing
  transaction. Every form keeps the selected child `Constructed` and disposal
  deferred until the callback returns.
- Add, insert, replacement, and factory or bulk population recheck destination
  viability after successful construction hooks. Destination disposal at that
  point rejects admission and restores the exact pre-call membership,
  lifecycle, selection, and population state.
- Replacement rollback restores the displaced child before any deferred
  disposal completes, so terminal disposal observes the rolled-back
  membership.
- `FWD-004` is the normative proof for canonical forwarding ownership.
  `COMP-026` and `COMP-040` explicitly cover the callback and rollback edges.

## 3. Consequences

- Wrapping is transparent to exclusive ownership without changing the public
  child identity retained by a collection.
- Opposing or structurally mutating callbacks cannot retain the global
  coordination lane while executing consumer code.
- Population and replacement failures cannot leave constructed or detached
  orphans, including when disposal is requested from a lifecycle hook.
- The clarification adds one library conformance ID but no public API, package
  version, fixture, or minimum-spec change.

## 4. Rejected alternatives

- Treat each decorator as a separate owner: this permits aliasing one component
  into multiple lifecycle and selection trees.
- Retain the shared coordinator through callbacks: consumer callback graphs can
  then acquire unrelated collection locks in reverse order.
- Let disposal win over rollback ordering: terminal cascades would observe an
  intermediate membership state rather than the operation's final result.
