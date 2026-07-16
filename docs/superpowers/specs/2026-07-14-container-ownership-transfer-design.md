# Container Ownership Transfer Design

## 1. Objective

Make container membership a single-owner relationship in every VMx flavor.
When a `CompositeVM` or `GroupVM` receives a child that belongs to a different
container, the operation removes the child from its old parent before adding it
to the new parent. Rust gains a usable internal parent link instead of tracking
only a numeric parent ID.

The change must reject duplicate membership and parent cycles, preserve child
lifecycle state during transfer, and leave all involved objects unchanged when
the destination operation fails.

## 2. Scope

This design applies to mutable child membership through composite and group
`Add`, `Insert`, indexed replacement, and bulk population paths. It also applies
to any builder or factory path that invokes those operations.

`HierarchicalVM` retains its existing explicit `reparentChild` operation. Its
parent link and cycle checks remain the model for transfer semantics, but its
observable tree messages are not added to ordinary composites or groups.

Fixed aggregate component slots are outside the transfer API because an
aggregate has no operation that can remove a component while preserving a
valid aggregate. Aggregate construction must reject a component that is
already owned by a mutable or fixed container rather than silently overwrite
its parent.

## 3. Ownership Contract

Each component has zero or one internal parent link:

- An unowned component has no parent.
- A component present in a composite or group has exactly that container as
  its parent.
- The same component instance cannot appear twice in one container.
- A component cannot be its own parent or be attached beneath one of its
  descendants.
- Removing a component clears the parent link without destructing or disposing
  the component.
- Adding a component owned by another mutable container transfers it. The old
  membership is removed first and the destination membership is added second.

The parent link remains internal and non-consumer-settable. Existing public
selection behavior and property-notification surfaces remain unchanged.

## 4. Parent-Link Architecture

C#, Python, TypeScript, and Swift retain their existing internal parent
reference or group-parent adaptor. Their internal parent protocol grows only
the operations needed by the ownership coordinator: stable parent identity,
membership lookup, transactional detach, and transactional restore.

Rust replaces `Option<usize>` as the authoritative relationship with an
internal weak parent handle. The handle exposes stable identity and type-erased
detach/restore operations by child identity. It must not strongly retain the
parent, and callbacks stored by the handle must capture parent state weakly so
that parent and child ownership cannot form an `Arc` cycle. The existing
`parent_id()` surface remains available and derives its value from the handle.

The internal link is deliberately narrower than a public container interface.
Consumers cannot use it to mutate membership, and flavors do not gain new
public parent setters.

## 5. Transfer Algorithm

Every destination mutation follows the same transaction:

1. Validate the destination index and all operation-specific arguments.
1. Reject self-parenting, ancestor cycles, and an instance already present in
   the destination.
1. Capture the old parent's identity, child index, selection state, and any
   other membership state needed for exact restoration.
1. Detach the child from the old parent without lifecycle transitions or
   external notifications.
1. Attach it to the destination and set the new parent link.
1. If destination policy requires construction of an unconstructed child,
   complete construction before committing the membership transaction.
1. Commit both containers' state, then publish the old-parent removal followed
   by the new-parent addition and relevant selection notifications.

No user callback, observable notification, or hub publication runs while an
internal ownership lock is held. Implementations use deterministic lock
ordering or avoid holding both parent locks concurrently.

Adding an instance already present in the same destination is an error rather
than a reorder or no-op. Existing move/reorder APIs remain the only way to
change an item's position within one container.

## 6. Failure and Rollback

All validation occurs before detaching from the old parent. If attachment or
auto-construction nevertheless fails, rollback restores:

- the child's original parent link;
- its original index in the old container;
- the old parent's current selection and child-current flags;
- the destination's exact pre-operation membership and selection state; and
- the child's lifecycle state as governed by the existing lifecycle rollback
  rules.

Failed operations publish no committed membership notifications. A rollback
failure is an invariant violation and must preserve the original operation
error as the primary failure while surfacing rollback diagnostics through the
flavor's established invariant/error mechanism.

Bulk population is transactional for the batch: if any child cannot be
attached or constructed, every earlier transfer in that population attempt is
restored. A lazy group is not marked populated until the full batch commits.

## 7. Specification and Compatibility

The language-neutral specification will state single ownership, automatic
cross-parent transfer, duplicate and cycle rejection, notification order, and
rollback guarantees in the component, composite, group, aggregate, and
lifecycle chapters. A new ADR records why automatic transfer was selected over
rejecting already-owned children or allowing DAG membership.

New conformance IDs cover:

- successful cross-parent transfer;
- removal-before-addition observation order;
- duplicate and cycle rejection without mutation;
- failed transfer rollback; and
- Rust's usable weak parent-link parity through the same observable behavior.

All five full-parity flavors receive real tests for every new ID. Version and
compatibility changes follow the repository's SemVer policy after the final API
impact is known; no public parent mutation API is planned.

## 8. Testing Strategy

Tests are written before implementation in each flavor. Focused tests first
demonstrate the current duplicate, stale-old-parent, cross-parent, cycle, and
rollback failures. Shared fixture scenarios use object identity rather than
model equality.

Each flavor then proves:

1. A child moves from old to new membership and reports only the new parent.
1. Removing from the old parent after transfer cannot clear the new parent.
1. The child is neither destructed nor disposed during transfer.
1. Same-parent duplicates, self-parenting, and ancestor cycles fail without
   state or notification changes.
1. Invalid destination indices do not detach the child.
1. Auto-construction failure restores the old index and selection exactly.
1. Batch failure restores every earlier transfer and leaves lazy population
   retryable.
1. Rust drops parent and child graphs without retaining an ownership cycle.

Focused suites are followed by all five flavor test, lint, formatting,
documentation, package, fixture, and conformance-coverage gates required by
the repository.

## 9. Documentation

Canonical documentation explains automatic transfer and explicit removal
semantics once. The generated MkDocs site and GitHub wiki are regenerated from
that source. Existing architecture diagrams are updated only if their ownership
arrows or component descriptions become inaccurate, then regenerated and
validated with the architecture-diagram workflow.

## 10. Non-Goals

- Public parent mutation or parent traversal APIs for ordinary components.
- Multiple simultaneous parents or DAG membership.
- Automatic disposal or destruction on removal or transfer.
- Replacing dedicated collection move/reorder operations.
- Changing `HierarchicalVM` tree-message semantics.
- Making fixed aggregate slots dynamically removable.
