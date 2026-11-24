# ADR 0249 — A released stored tree root falls back to the parent links

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec version:** 3.30.0 (chapter 18 §7, `HIER-018`; no conformance ID change; no library behavior change in this pull request)
- **Amends:** [ADR-0248](0248-attach-cycle-check-by-tree-root.md) §2.3. Related:
  [ADR-0247](0247-hierarchy-root-pointer.md) §2.3 and §3,
  [ADR-0037](0037-v2.5-maintenance-clarifications.md) (`HIER-018`), #1912.

## 1. Context

ADR-0248 §2.3 says that every `HierarchicalVM` node stores its tree root and that
"the stored root must always be correct, so no lookup falls back to a parent
walk." ADR-0247 D1 makes the stored link weak. A strong link from each node to
its root would form a reference cycle with the children, so no root keeps itself
alive. A weak link can be released while a descendant is still held. A handle to
a descendant keeps that descendant alive, not its ancestors. When the root is
released, the stamp of every surviving node names nothing.

The Rust implementation of ADR-0248 (`root_unlocked` in
`langs/rust/src/hierarchical.rs`) and the Swift implementation of the same rule
(`treeRoot()` in `langs/swift/Sources/VMx/Hierarchical/HierarchicalVM.swift`)
both walk the parent links from such a node to the top of its surviving chain.
The Rust test `a_node_whose_root_was_dropped_finds_the_top_through_its_parents`
pins that walk. So ADR-0248 §2.3 and the code disagree. The contradiction is not
a correctness fault: the walk returns the top of the surviving chain, which is
the correct answer for the cycle check. It is a contract fault, because the text
forbids the walk that the code performs.

## 2. Decision

### 2.1 Stored root and released root (ADR-0248 §2.3 amended)

A lookup of a node's tree root reads the stored root first.

- When the stored root is live, the lookup returns it in O(1) and walks nothing.
  This is the normal case, and every attach, move and detach takes it.
- When the stored root has been released, the lookup walks parent links from the
  node to the top of its surviving chain, in O(depth), and returns that top. The
  walk runs only in this case. It does not restamp the nodes it passes, because a
  lookup changes no state.

The rule for a stored root is: correct while its node is live, and answered by the
parent links after it is released. ADR-0248 §2.3 keeps the rest of its text. Its
restamp, its traversal and its cost in §3 are unchanged.

### 2.2 Choice among the options (decision record)

Three ways to satisfy the original rule were weighed. The owner delegated this
kind of choice, so the simplest option that is uniform across flavors is taken.

- **(a) Chosen.** Allow the parent walk only for a released stored root. The code
  and the existing test already do this, so the change is textual. The normal
  path costs O(1). A lookup on a subtree whose root was released costs O(depth)
  until a later attach or move restamps that subtree.
- **(b) Rejected.** Restamp the surviving subtrees when the root is released, in
  its `Drop`. `HIERARCHY_TOPOLOGY_GATE` is not reentrant, and the last handle to a
  node can be dropped while the gate is held. The `retain` calls in `attach_child`
  and `rollback_batch_attach` are examples. A restamp there could deadlock or race.
- **(c) Rejected for this decision.** A lazily validated root with path
  compression. ADR-0248 §3 names it as a later alternative and not part of that
  decision. It still walks on the first lookup after a release, so it does not
  remove the walk.

### 2.3 Flavors

The walk is reachable only where the stored root is a weak link. In Rust
(ADR-0247 D1) and Swift (`rootLink`, a `weak var`), it is reachable. A grep of the
C#, Python and TypeScript pull-request branches finds no weak tree-root link, so
in those flavors no stored root can be released while a node holds it. The rule
above therefore reads the same in every flavor, and each flavor's pull request
must not take a different rule.

### 2.4 Scope

This ADR adds no public API, no error text, no conformance ID and no version bump.
It changes no library code. Its changes under `spec/` are this file, the Status
back-link of ADR-0248, the registry cell of ADR-0248, and the registry row of this
ADR. No spec chapter changes.

## 3. Consequences

- The text of ADR-0248 §2.3 matches the Rust and Swift code and the Rust test.
- The cost of a lookup on a node whose root was released is O(depth) until the
  subtree is restamped. The cost of every other lookup is O(1), as before.
- The walk answers with the top of the surviving chain. The cycle check of
  ADR-0248 §2.2 therefore stays correct after a root is released.
- Swift's pending flavor pull request for #1912 already has this walk. This ADR
  covers it, so that pull request needs no new decision.

## 4. Rejected alternatives

- **Remove the walk and return no root for a released stamp.** Rejected. The cycle
  check of ADR-0248 §2.2 would then have no answer for a node in a surviving chain,
  and it could admit a cycle.
- **Options (b) and (c) of §2.2.** Rejected for the reasons given there.
