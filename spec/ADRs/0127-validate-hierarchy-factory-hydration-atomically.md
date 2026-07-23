# ADR 0127 — Validate hierarchy factory hydration atomically

**Status:** Accepted (2026-07-23)
**Spec version:** introduced in 3.22.1
**Extends:** [ADR-0028](0028-hierarchical-vm.md), [ADR-0105](0105-atomic-hierarchy-attachment.md)

## 1. Context

Lazy hierarchy factories previously assigned each returned node's parent
without validating the complete result. Duplicate identity, self/ancestor
references, or nodes already owned by another parent could therefore corrupt
the tree. A late failure could also leave a partially mutated snapshot.

## 2. Decision

- Snapshot the complete factory result before structural mutation.
- Preflight null-like entries, duplicate object identity, this node or any
  ancestor, and every node whose parent is already non-null. Factory hydration
  never implies transfer, even when the existing parent is the receiver.
- Reject the complete snapshot without installing the child cache, changing
  any parent/path state, or publishing messages. A later access retries the
  factory.
- Commit a valid snapshot in factory order by assigning parent backpointers
  silently, invalidating any detached-node path caches, and installing the
  cache only after validation succeeds.
- Reject structural re-entry by the factory on its receiver, including add,
  remove, reparent, batch attach, and cache invalidation. The outer hydration
  attempt remains uncommitted and retryable even when the nested API cannot
  surface an error directly.
- Keep ordinary `AddChild` as the explicit transfer API.
- Swift adds `tryChildren() -> Result<[TVM], HierarchyError>` and Rust adds
  `try_children() -> VmxResult<Vec<Self>>`; their existing `children` accessors
  delegate and fail fast for source compatibility. Other flavors use their
  existing invalid-operation error surfaces.
- Rust performs validation and commit under its topology gate. No broader
  concurrency guarantee is introduced for the other synchronous flavors.

## 3. Consequences

- Factory hydration is structurally atomic, silent, ordered, and retryable.
- Factories must return newly detached node identities; callers that intend to
  transfer nodes use `AddChild`.
- `HIER-031` covers valid hydration, including stale detached path caches, plus
  duplicate, self/ancestor, and already-parented rejection in all five flavors.
- `HIER-032` covers same-receiver structural re-entry, atomic rejection, and
  retryability in all five flavors.

## 4. Rejected alternatives

- Reuse `AddChild` for every factory result: this would transfer existing nodes
  and publish mutation messages during initial hydration.
- Validate while assigning parents: a later invalid item could expose partial
  state.
- Accept duplicate references: one object cannot have two structural positions
  under the same parent while preserving path and sibling invariants.
