# ADR 0247 — Hierarchy root pointer and iterative subtree invalidation

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec version:** 3.30.0 (chapter 18 §5 clarified; no conformance ID change; no library behavior change)
- **Clarifies:** [ADR-0073](0073-hierarchical-child-cache-invalidation.md) §2 (the reach of `InvalidateSubtree`; the traversal is not specified). Related: [ADR-0028](0028-hierarchical-vm.md) §3 item 5, [ADR-0037](0037-v2.5-maintenance-clarifications.md) §2.3, [ADR-0127](0127-validate-hierarchy-factory-hydration-atomically.md), [ADR-0170](0170-tree-walks-report-invalid-factory-output.md), [ADR-0189](0189-disposed-children-leave-current-and-container-walks.md), [ADR-0190](0190-disposed-tree-nodes-refuse-structural-calls.md), #1912.

## 1. Context

Issue #1912 asks that tree walks, `depth`, path-cache invalidation and the attach
cycle check cost no stack frame per tree level, and no ancestor walk per attach.
Chapters 13 and 18 set no depth limit.

Pull request #2061 (Python and TypeScript) and pull request #2202 (C#, Swift and
Rust) made `walk`, `walk_expanded`, `find`, `depth` and path-cache invalidation on
move iterative. Three problems remain on `develop`. The measurements below were
taken on macOS against `origin/develop` 3b027405 and the pre-fix parents.

1. **`invalidateSubtree` still recurses once per level** in every flavor. On
   `develop` it fails at 974 to 1036 levels in Python, at 2468 in TypeScript, at
   8000 to 8500 in C# with a 512 KiB stack, at 2180 in Swift with a 512 KiB
   thread, and at 5625 to 6062 in Rust.
1. **Each attach walks the receiver's ancestors** for the cycle check. Building a
   chain of N nodes therefore costs O(N²). The ratio of build, full walk and
   depth at 2N and at N on `develop` is 5.13 (Python), 4.39 (TypeScript), 4.77
   (C#), 3.97 (Swift) and 4.99 (Rust). A balanced tree of the same size gives
   about 2. In TypeScript, with the ancestor scan removed, the time is 72.6 ms at
   10,000 levels and 139.4 ms at 20,000 levels.
1. **Swift walks to the root once per node** to check for a cycle when it
   materializes children, which is the same O(N²) cost as item 2.

Before pull requests #2061 and #2202, the first failures on the pre-fix parents
were: Python at 1036 levels, at the default recursion limit of 1000, for `walk`,
`depth` and move; TypeScript `walk` at 4149 to 4525, `depth` at 2468 to 2691 and
move at 4934 to 5381; C# `walk` at 4750 to 5000 with JIT tiering off and at 1500
to 1625 with it on, and move at 6250 to 6875 with a 512 KiB stack; Swift `walk` at
1147 to 1228 with a 512 KiB thread; Rust `walk` at 2687 to 2968 and `depth` at
8312 to 8875 with a 2 MiB stack.

## 2. Decision

### 2.1 Root pointer (D1)

Each `HierarchicalVM` node holds a reference to its tree root. A root holds
itself. A child takes its parent's root when it attaches. When a subtree moves,
reparents or detaches, every materialized node in the moved subtree is restamped
with the new root, in one iterative traversal. C#, Python, TypeScript and Swift
already invalidate the path cache on move, so the restamp goes into that same
traversal.

### 2.2 Cycle check (D2)

A candidate with no parent is a cycle when it is this node or this node's root.
Otherwise it attaches. A parentless node can be an ancestor of this node only when
it is the root of this node's tree, so this rule is complete. An attach of a
parentless node costs O(1), and so does its rejection.

A candidate that already has a parent is checked by a walk of this node's
ancestors, which costs O(depth of this node). For a move (`add_child` or
`reparent_child`), the walk finds a cycle. Rust skips the walk for a candidate in
another tree, which cannot be an ancestor of this node. A children-factory result
that already has a parent also walks, to choose between the cycle message and the
already-parented message. Error texts do not change.

### 2.3 Iterative subtree invalidation (D3)

`invalidateSubtree` and every other recursion over the materialized subtree use an
explicit stack. They are: Python `_invalidate_subtree_nodes`; TypeScript
`invalidateSubtree` and `invalidateDescendant`; C# `InvalidateSubtree` and
`DropSubtree`; Swift `invalidateMaterializedSubtree`; and Rust
`invalidate_subtree_from_live_ancestor`. The traversal visits nodes in the same
order as the recursive code and skips disposed nodes exactly as it does now. The
reach does not change: every currently materialized descendant, at any depth.
Chapter 18 §5 said that `InvalidateSubtree` applied its invalidation "recursively".
ADR-0247 replaces that word with "at any depth", which names the reach and not the
call mechanism. The traversal is not specified (`spec/HISTORY.md`, v3.30.0). The
replacement landed with this ADR in #2221, on develop, so this pull request
changes no spec text.

### 2.4 Storage (D4)

Python, TypeScript and C# use a plain reference for the root link, because their
parent links are plain references today. If a flavor's parent link is weak, its
root link is weak too. Swift keeps a weak reference beside the path cache, to avoid
an ARC cycle with the children array. Rust uses a `Weak` handle, as Rust nodes
already hold their parent, so there is no `Rc` cycle.

### 2.5 Scope (D5)

This change adds no public API, no conformance ID and no version bump. The only
change under `spec/` is the clarification in chapter 18 §5, made in the same pull
request as this ADR. The flavor pull requests change no file under `spec/`. Each
flavor pull request adds a `### Fixed` entry under its unreleased source version
heading in its CHANGELOG. This pull request changes no library code, so it adds no
CHANGELOG entry.

### 2.6 Tests (D6)

Each flavor adds an `invalidateSubtree` test on a 10,000-level chain to its
existing deep-chain test file. The test uses the same depth constant as that file's
walk, depth and move tests. Removing the restamp on move makes the move test fail.

### 2.7 Linearity (D7)

Where a benchmark harness exists (`benchmarks/python/run.py` and
`benchmarks/typescript/run.mjs`), a case times build, full walk and depth at N and
at 2N, and reports the ratio. The expected ratio after the fix is about 2. Before
the fix the measured ratios were 3.97 to 5.13. Where no harness exists, the same
ratio is measured with a script kept in the scratchpad, and the numbers go in the
pull request body. Timing is never a CI gate.

### 2.8 Out of scope (D8)

The component-level attach cycle checks also walk ancestors on each attach:
`langs/python/src/vmx/components/base.py` lines 448 to 454, and
`langs/typescript/src/components/parentTransfer.ts` lines 146 to 151. This ADR
does not change them. The flavor pull requests measure the cost they add to the
build case and report it in their bodies. The recursive Rust drop is issue #2204.

### 2.9 Rust move trade (D9)

The restamp adds O(materialized subtree) to a Rust move. The same-tree cycle walk
of §2.2 still costs O(depth of the new parent), so a Rust move costs O(depth of
the new parent + materialized subtree), where it cost O(depth of the new parent)
before. The restamp is accepted for uniformity across flavors.

## 3. Consequences

- Each node stores one more reference, to its root.
- An attach of a parentless node costs O(1). A move costs one O(depth of the new
  parent) cycle walk, plus O(materialized subtree) for the restamp or path-cache
  invalidation, in every flavor. Each rejected attach keeps its error text.
- In Rust a move of a parented node in another tree skips the cycle walk, so it
  costs O(materialized subtree) only, as §2.9 records.
- Python's parent link is a strong reference, so a root that holds itself is a
  reference cycle. Python frees such a root with its cyclic collector, not by
  reference counting. A tree with materialized children already forms cycles
  through its parent and children links, so the collector already handles these
  trees.
- Swift's root link is weak, so a root does not keep itself alive.
- The new tests use 10,000 levels. That depth is a documented choice for the tests,
  not a limit. It is far past the depths in §1 where the old code failed. No
  flavor limits depth after this change, and chapters 13 and 18 set no limit.

## 4. Rejected alternatives

- **Keep an ancestor set on each node.** Rejected. Each node would copy a set
  whose size is its depth, so materializing a chain of N nodes costs O(N²).
- **Check only the root, with no separate error path.** Rejected. The existing
  error messages depend on the ancestor walk, so they would change.
- **Read the root from the path cache.** Rejected. Each node's path cache is a copy
  of its whole path, so the caches of a chain cost O(N²) memory.
