# ADR 0248 — Attach cycle check by tree root

- **Status:** Accepted (§2.3 amended by ADR-0249)
- **Date:** 2026-11-23
- **Spec version:** 3.30.0 (chapter 18 §7, `HIER-018`; no conformance ID change; no library behavior change in this pull request)
- **Amends:** [ADR-0247](0247-hierarchy-root-pointer.md) §2.2, §2.9 and §3. Related:
  [ADR-0037](0037-v2.5-maintenance-clarifications.md) (`HIER-018`),
  [ADR-0127](0127-validate-hierarchy-factory-hydration-atomically.md),
  [ADR-0170](0170-tree-walks-report-invalid-factory-output.md),
  [ADR-0189](0189-disposed-children-leave-current-and-container-walks.md),
  [ADR-0190](0190-disposed-tree-nodes-refuse-structural-calls.md), #1912.

## 1. Context

ADR-0247 §2.2 makes every successful attach cost O(1). A candidate that already
has a parent takes the already-parented error path. Chapter 18 §7 makes an
explicit reparent a legal move: `AddChild` transfers a child that another parent
owns, and it publishes one `Reparented` message. The flavor pull requests for
ADR-0247 (#2222 to #2225) found that such a move must still check for a cycle.
A node moved under one of its own descendants corrupts `Depth`, `Path` and
`walk`, and HIER-018 forbids it. ADR-0247 §2.2 cannot allow the move, because it
rejects every candidate that has a parent. An ancestor walk on every move costs
O(depth) each time, which is the cost that ADR-0247 removed from attach.

This ADR keeps ADR-0247 §2.2 for factory materialization and batch attach, which
is rule R1. For explicit add and reparent it sets rules R2 and R3. They compare
stored tree roots, so a move walks ancestors only in case (d) of R2.

## 2. Decision

### 2.1 Factory materialization and batch attach (R1)

A candidate that already has a parent is rejected with the existing error:
already-parented for a factory child, and the existing `AttachmentFailed` or
`AlreadyAttached` rejection for a batch item. The ancestor walk runs only on that
error path, to choose the existing message. A successful attach costs O(1) for
its cycle check. Its restamp is covered by R3.

### 2.2 Explicit add and reparent (R2)

These checks run in this order, before any mutation, as chapter 18 §7 requires.

(a) The candidate is the receiver. The result is the cycle error, with the
existing message.

(b) The candidate and the receiver have different stored roots. No cycle is
possible, so the cycle check costs O(1), and the transfer proceeds.

(c) The two have the same stored root, and the candidate has no parent. The
candidate is then that root, so it is an ancestor of the receiver. The result is
the cycle error, in O(1).

(d) The two have the same stored root, and the candidate has a parent. Walk the
receiver's ancestors. If the candidate is one of them, the result is the cycle
error. Otherwise the transfer proceeds. Only (d) costs O(depth of the receiver).

### 2.3 Stored tree root (R3)

Every `HierarchicalVM` node stores its tree root. A root stores itself. Attach,
reparent, detach and materialization set the stored root. The root of every
materialized node in an attached or moved subtree is restamped in one iterative
traversal, which also clears path caches where the flavor already does so. The
stored root must always be correct, so no lookup falls back to a parent walk.

### 2.4 Error texts and public API (R4)

Error texts and the public API do not change. Subtree invalidation is iterative,
as ADR-0247 §2.3 says, and it is unchanged here.

### 2.5 Amended sections of ADR-0247

ADR-0247 keeps its decision text. From this ADR on, its three amended sections
read as follows.

- **§2.2** applies to explicit add and reparent through R2 and R3. For factory
  materialization and batch attach it still applies, as R1 states. Its
  already-parented error path and its rule that error texts do not change are
  unchanged.
- **§2.9** reads: the restamp costs O(materialized subtree) for a move in Rust, as
  in every flavor. A move also pays the cycle check of R2, which costs
  O(depth of the receiver) only in case (d). The change is accepted for
  uniformity across flavors.
- **§3** reads, for its attach and move bullets:
  - An attach that succeeds costs O(1) for its cycle check. Its restamp costs
    O(materialized nodes of the attached subtree).
  - A rejected factory or batch attach costs one O(depth) walk, and its error
    text is unchanged.
  - A move costs O(materialized subtree) for its restamp in every flavor. Its
    cycle check costs O(depth of the receiver) only in case (d) of R2.

### 2.6 Scope

This ADR adds no public API, no conformance ID and no version bump. It changes no
spec chapter. Its changes under `spec/` are this file, the registry rows of
ADR-0247 and ADR-0248, the Status back-link of ADR-0247, and one sentence in
section 39 of `spec/HISTORY.md` that names this ADR. Each flavor pull request adds
its own CHANGELOG entry.

## 3. Consequences

- Each node stores one more reference, to its tree root. The stored root is
  always correct, so no lookup walks parents.
- An explicit add or reparent costs O(1) for its cycle check, except case (d) of
  R2, which costs O(depth of the receiver). Case (d) is a move within one tree.
- The restamp costs O(materialized nodes in the attached or moved subtree).
  Path-cache invalidation already visits that subtree on attach in C#, Python,
  TypeScript and Swift, so the restamp adds no new order there. Rust has no path
  cache, so bottom-up construction (attach a subtree that already holds many
  materialized nodes, from the leaf up) becomes O(N²) in Rust, where it was
  linear before. This is accepted for uniformity across flavors. A later
  alternative is a lazily validated root with path compression. It is not part of
  this decision.
- A rejected attach costs one O(depth) walk only on the already-parented error
  path, and its error text is unchanged.

## 4. Rejected alternatives

- **Always walk the ancestors.** Rejected. Each explicit add or reparent would
  cost O(depth of the receiver), which is the cost that ADR-0247 removed from
  attach.
- **A stored root with no cross-tree shortcut.** Rejected. It is correct, but it
  costs an ancestor walk for every move, including the moves of cases (a) to (c),
  which need none.
