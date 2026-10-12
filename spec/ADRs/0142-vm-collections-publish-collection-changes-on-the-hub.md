# ADR 0142 — VM collections publish their collection changes on the message hub

- **Status:** Accepted
- **Date:** 2026-10-12
- **Spec version:** 3.26.0
- **Amends:** [ADR-0024](0024-hub-aware-observable-collection.md) §2 option 2,
  which this ADR adopts for `CompositeVM` and `GroupVM`
- **Related:** [ADR-0085](0085-shared-vm-collection-move.md) (shared VM
  collection capability; Rust's hub-backed stream is the precedent),
  [ADR-0009](0009-cross-flavor-divergence-catalogue.md) §2.15

## 1. Context

`CompositeVM` and `GroupVM` raise their collection changes only on the
container's local stream in C#, Python, TypeScript, and Swift. A subscriber
that observes a VMx graph through the message hub therefore sees
`HierarchicalVM` edits, which publish `TreeStructureChangedMessage`, but never
an add, remove, replacement, move, or clear on a composite or group.

The gap surfaced in a downstream renderer that is a pure hub subscriber
(#579). It never drew a root added with `CompositeVM.add` until a reload, so the
application added a per-instance pass-through stream only to work around the
silent container. VMx's own React adapter has the same gap: `createVmxStore`
invalidates only on hub messages, so a snapshot such as `composite.length`
goes stale after an add.

Rust is already different. Its composites and groups keep their children in a
hub-bound `ObservableList`, which publishes a `CollectionChangedMessage` for
each change, one `Reset` on batch exit, and `PropertyChanged("Count")` when the
size changes (ADR-0085, ADR-0009 §2.15).

ADR-0024 §2 considered "Extend `CompositeVM` to publish its own
`CollectionChanged` to the hub" and chose a standalone opt-in collection
instead, so that plain collections could publish too. That choice stands for
`ServicedObservableCollection<T>`; it did not consider hub-only observers of a
VM graph.

## 2. Options considered

1. **Keep containers local-only.** Every hub-only observer wires each
   container's local stream by hand, and the React adapter needs a separate
   subscription per container.
1. **Opt-in publication per container.** A flag or builder option enables
   publication. Observers still cannot rely on the hub without knowing how each
   container was built, and the flavors gain a configuration surface Rust does
   not have.
1. **Always publish, as Rust does.** One observation channel covers every
   structural change in a VMx graph.

## 3. Decision

Option 3. Every `CompositeVM` and `GroupVM` publishes its collection changes to
its own message hub:

1. **One message per local event.** Each effective local collection-change
   event is followed by exactly one `CollectionChangedMessage` (chapter 21
   §2.4) sent to the container's hub. The container is the sender. The message
   carries the same action and positions as the local event and, in the typed
   flavors, the same items. Replacement keeps each flavor's established local
   decomposition (ADR-0085), so the hub sees the same sequence the local stream
   sees.
1. **Local first.** The local event is delivered before the hub message, the
   order ADR-0024 §3 fixes for serviced collections. Both channels observe the
   committed membership.
1. **Batches.** Nothing is published inside a batch. When the outermost scope
   completes normally after at least one mutation, one `Reset` message follows
   the local `Reset`. An empty batch, or one containing only same-index moves,
   publishes nothing.
1. **Ownership transfer.** A transfer between two containers publishes the old
   container's `Remove` before the new container's `Add`, matching the local
   commit order of chapter 06 §4.2. A failed preflight, a rolled-back transfer,
   and a same-index move publish nothing, because they raise no local event.
1. **Delivery.** Publication goes through the hub's ordinary `Send`, so a hub
   transaction defers the messages in FIFO order (chapter 03 §3.3) and a null
   hub discards them. Publication happens on the mutating thread with no
   dispatcher marshalling. A disposed container publishes nothing.
1. **Forwarding.** A forwarding composite wrapper owns no membership and
   publishes nothing of its own, so each change reaches the hub once, sent by
   the container that owns it.

Rust keeps its established message shape (`sender_id` with optional
positions) and its additional `PropertyChanged("Count")` message, which ADR-0085
records. The other flavors do not add a hub `Count` message; their local count
notifications are unchanged.

Out of scope: filtered and paged composite views, `HierarchicalVM` (which
already publishes `TreeStructureChangedMessage`), aggregate VMs, and an opt-out
switch.

## 4. Consequences

- Chapter 01 §1.4 states the rule for the shared VM collection capability.
  Chapters 06 (§4, §4.1, §4.2) and 07 refer to it, and chapter 21 §2.4 names
  the containers as publishers of `CollectionChangedMessage`.
- `COMP-042..045` and `GRP-012..013` cover per-event publication, batch
  coalescing, transfer order and failed mutations, and delivery through hub
  transactions, disposal, and forwarding wrappers.
- C#, Python, TypeScript, and Swift add publication to their containers. Rust
  already published each change and batch `Reset`, but a disposed container
  kept publishing removals, moves, clears, and a pending batch `Reset`; it now
  stops publishing when disposal starts, and adds the conformance tests.
- **Compatibility.** Hub subscribers now receive `CollectionChangedMessage`
  from containers. A subscriber that filters by message type is unaffected; one
  that handles every message, or counts them, sees the additional traffic. The
  React adapter's `useVmx` now re-renders after a membership change. This is a
  minor spec bump to 3.26.0.
