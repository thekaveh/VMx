# ADR 0107 — Transfer container ownership atomically

**Status:** Accepted (2026-07-14)
**Spec version:** introduced in 3.21.0

## 1. Context

Every component carries an internal `Parent` back-reference, but composite and
group mutations previously overwrote that reference without removing the child
from its old container. The same identity could therefore remain in two lists;
removing it from the old list later cleared the newer parent; duplicates and
parent cycles were also accepted. Construction or index failures could leave a
ghost parent or partial membership.

Rust exposed only a numeric `parent_id`, so unlike the other flavors a child had
no usable relationship through which its old parent could coordinate removal.
ADR-0105 already establishes atomic attach-or-transfer for `HierarchicalVM`.
Ordinary composite and group ownership needs the same invariant without taking
on hierarchy-specific tree messages.

## 2. Decision

A component has zero or one owning container. `Add`, `Insert`, replacement, and
builder population preflight destination indices, duplicate identity, and
self/ancestor cycles before mutation. Adding a child owned by a different
mutable container stage-detaches it from the old parent, attaches and
auto-constructs it in the destination, then commits the old removal before the
new addition notification. Transfer never destructs or disposes the child.

If attachment or construction fails, both containers, the parent link, index,
selection state, child-current flags, lifecycle state, and lazy-population state
are restored exactly. A failed transaction publishes no membership event.
Bulk population commits only after the whole batch succeeds.

Parent links remain internal. Flavors with tracing garbage collection keep
their internal parent reference/adaptor. Swift keeps it weak. Rust stores a weak
type-erased parent owner rather than an authoritative numeric ID;
`parent_id()` remains a derived compatibility accessor. No child-to-parent link
may keep an otherwise unreachable parent alive.

Fixed aggregate slots cannot be detached while preserving a valid aggregate,
so aggregate construction rejects a component that is already owned instead
of transferring it.

Swift preserves the `VMCollection` protocol's existing `Void` mutation methods
and follows ADR-0105's source-compatible error pattern through companion
`addResult`, `insertResult`, and `replaceResult` methods. Callers that need
rejection details can inspect the typed `Result`; existing ignored-success calls
remain source compatible.

## 3. Consequences

- One component identity cannot remain in two containers.
- Removing from an old container cannot clear a newer parent link.
- Same-container duplicates and ownership cycles fail before mutation.
- Subscribers observe removal before addition only after a successful transfer.
- Rust can coordinate real ownership transfer and does not form an `Arc` cycle.
- Transfer and ordinary removal preserve child lifecycle state and resources.

## 4. Rejected alternatives

- Require explicit removal before every cross-parent add: simpler, but rejects
  the established automatic-reparent intent and diverges from ADR-0105.
- Allow multiple parents: selection delegation, current state, disposal, and
  parent-derived commands require one authoritative owner.
- Publish removal immediately and compensate with a later add on failure:
  exposes a transaction that the contract says did not happen.
- Store a strong Rust parent handle: creates a parent-child `Arc` cycle.
