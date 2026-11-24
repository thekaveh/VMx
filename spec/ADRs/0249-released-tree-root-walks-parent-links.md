# ADR 0249 — A released stored tree root falls back to the parent links

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec version:** 3.30.0 (chapter 18 §7, `HIER-018`; no conformance ID change; no library behavior change in this pull request)
- **Amends:** [ADR-0248](0248-attach-cycle-check-by-tree-root.md) §2.1, §2.2, §2.3 and §3.
  Related: [ADR-0247](0247-hierarchy-root-pointer.md) §2.3 and §2.5 (corrected in §2.6 below),
  [ADR-0037](0037-v2.5-maintenance-clarifications.md) (`HIER-018`), #1912.

## 1. Context

ADR-0248 §2.3 says that every `HierarchicalVM` node stores its tree root, and that
"the stored root must always be correct, so no lookup falls back to a parent
walk." That rule does not hold in Rust and Swift. ADR-0247 §2.4 makes their stored
root a weak reference. A strong root link would make every root own itself through
a reference cycle (`Arc` in Rust, ARC in Swift), so no tree would ever be freed.
A weak link can be released while a descendant is still held, because a handle to
a descendant keeps that descendant alive and not its ancestors. Parent links are
weak in both flavors for the same reason. When the root is released, the stored
root of every surviving node names nothing.

Rust and Swift already answer that case with a walk. Rust's `root_unlocked`
returns the stored root while it is live, and otherwise walks the parent links to
the top of the surviving chain. Swift's `treeRoot()` does the same. The Rust
function is at `langs/rust/src/hierarchical.rs` lines 380-396, and the Swift
function is at `langs/swift/Sources/VMx/Hierarchical/HierarchicalVM.swift` lines
774-779. Both are on the pull request branches for #1912, not on `origin/develop`
yet. The commits are named in §2.2. Rust's test
`a_node_whose_root_was_dropped_finds_the_top_through_its_parents` (same Rust file,
lines 1749-1776) pins the walk. So the text of ADR-0248 §2.3 and the code disagree.
This is a contract fault, not a correctness fault. The walk returns the top of the
surviving chain, which is the right answer for the cycle check.

The stored root also sets the cost of the attach checks. Factory materialization
(ADR-0248 R1) and explicit add or reparent (R2) read stored roots. Each read of a
released root adds one O(depth) walk. The O(1) costs in ADR-0248 §2.1, §2.2 (b) and
(c), and §3 hold only while those roots are live.

## 2. Decision

### 2.1 Released stored root (ADR-0248 R3 amended)

A lookup of a node's tree root reads the stored root first.

- While the stored root is live, the lookup returns it in O(1) and walks nothing.
  This is the normal case.
- After the stored root has been released, the lookup walks the parent links from
  the node to the top of its surviving chain, in O(depth of that chain), and returns
  that top. A lookup changes no state, so the walk restamps no node.

The rule is that the stored root answers while its node is live, and the parent
links answer once the stored root is released. The restamp and the traversal of
ADR-0248 §2.3 do not change.

### 2.2 Flavors

Rust and Swift implement the released case, because their stored root is weak.

- Rust stores `root: Mutex<Weak<...>>` (`langs/rust/src/hierarchical.rs` lines
  138-140, commit 21b9f1f8 on `fix/1912-rust-hierarchy-root`).
- Swift stores `private weak var rootLink: TVM?` (`HierarchicalVM.swift` line 154,
  commit 1214e70a on `fix/1912-swift-hierarchy-root`).

C#, Python and TypeScript store a strong reference, so the released case cannot
occur in them.

- Python stores `_structural_root: TVM = self` (`langs/python/src/vmx/hierarchical/hierarchical_vm.py`
  line 177 on `origin/develop`), next to the strong parent `_hierarchical_parent`
  (line 175).
- TypeScript stores `#root: TVM` (`langs/typescript/src/hierarchical/hierarchicalVm.ts`
  line 113 on `origin/develop`), next to the strong `#hierarchicalParent` (line 111).
- C# stores `private TVM _treeRoot;` (`langs/csharp/src/VMx/Hierarchical/HierarchicalVM.cs`
  line 35, commit d51a0815 on `fix/1912-csharp-hierarchy-root`), next to the strong
  `_hierarchicalParent` (line 32). C# is not on `origin/develop` yet.

Because a node holds a strong reference to its root, the root stays alive as long
as the node does, and a detached node stores itself. So the stored root of these
three flavors is never released while its node is alive, and they need no walk.
No flavor may take a different rule. A flavor whose stored root is weak must answer
a released root by §2.1.

### 2.3 Choice among the options (decision record)

Three ways to answer a released root were weighed. The owner delegated this kind of
choice, so the simplest option that is uniform across flavors is taken.

- **(a) Chosen.** Walk the parent links only for a released stored root. The Rust
  code and its test already do this, and the change to the text is the only change
  needed. The normal path costs O(1).
- **(b) Rejected.** Restamp the surviving subtrees when the root is released, in its
  `Drop`. A `Drop` runs wherever the last handle to a node is dropped, and Rust
  drops handles while `HIERARCHY_TOPOLOGY_GATE` is held. Two examples are the
  `retain` calls at line 501 of `attach_child` and at line 1195 of
  `rollback_batch_attach` on the Rust branch. Both drop removed children under the
  gate. The gate is a `Mutex<()>` (`langs/rust/src/runtime.rs` line 16 on
  `origin/develop`), and it is not reentrant. A `Drop` that took the gate could
  deadlock, and a `Drop` that did not could race a restamp in progress.
- **(c) Rejected for this decision.** A lazily validated root with path compression,
  which ADR-0248 §3 names as a later alternative. It still walks on the first lookup
  after a release, so it does not remove the walk.

### 2.4 Costs of the fallback

The fallback costs the following.

- A read of a released stored root costs one O(depth) walk, where the depth is that
  of the surviving chain. A read of a live stored root costs O(1), as before.
- The walk repeats on every read. A node's stamp changes only when the node, or one of
  its surviving ancestors, is attached, moved or detached, because each of those
  restamps the subtree that contains the node. Attaching a new child under a node
  restamps only that child's subtree. So each later add under a node whose root was
  released walks again, until one of those events reaches it.
- Missing-parent items are parked on the structural root (`parked_attach_items`).
  A released root takes the items parked on it, and the walk does not carry them to
  the top of the surviving chain.

### 2.5 Amended sections of ADR-0248

ADR-0248 keeps its decision text. From this ADR on, its amended sections read as
follows.

- **§2.1, §2.2 (b) and (c), and the cost bullets of §3** keep their cases and their
  results. Each O(1) cost in them holds while the stored roots that the check reads
  are live. A read of a released stored root costs one O(depth) walk of parent
  links, as §2.1 above states.

- **§2.3** reads: "Every `HierarchicalVM` node stores its tree root. A root stores
  itself. Attach, reparent, detach and materialization set the stored root. The root
  of every materialized node in an attached or moved subtree is restamped in one
  iterative traversal, which also clears path caches where the flavor already does
  so. While the stored root is live, a lookup returns it in O(1). After the stored
  root is released, a lookup walks the parent links to the top of the surviving
  chain (ADR-0249 §2.1)."

- **§3**, its first two bullets read:

  - "Each node stores one more reference, to its tree root. While the stored root is
    live, a lookup reads it in O(1). After the stored root is released, a lookup
    walks the parent links (ADR-0249 §2.1)."
  - "An explicit add or reparent costs O(1) for its cycle check while the stored
    roots it reads are live, except case (d) of R2, which costs O(depth of the
    receiver). Case (d) is a move within one tree. A released stored root adds one
    O(depth) walk for the node that holds it."

  The other bullets of §3 are unchanged.

### 2.6 Errata to ADR-0247

ADR-0247 §2.3 and §2.5 say that the chapter 18 clarification is part of the pull
request that carries ADR-0247, and that it names the reach of `InvalidateSubtree`.
That is corrected here. The chapter 18 change on `origin/develop` is a replacement,
not a sentence. The word "recursively" in chapter 18 §5 was replaced by "at any
depth", and pull request #2221 wrote that change (commit 45cd711e). Chapter 18 §5 now
says that `InvalidateSubtree` applies the same invalidation to this node and all
currently materialized descendants, at any depth. That names the reach. The text
has no sentence about the call mechanism, and the traversal stays unspecified, as the
ADR-0247 header says. No other text of ADR-0247 changes. Its Status and its registry
cell carry the back-link to this ADR.

### 2.7 Scope

This ADR adds no public API, no error text, no conformance ID, no spec chapter
change and no version bump, and it changes no library code. Its changes under
`spec/` are this file, the Status and registry cell of ADR-0247 (the errata
back-link), the Status and registry cell of ADR-0248 (the amended-by back-link), the
registry row of this ADR, and one sentence in section 39 of `spec/HISTORY.md` that
names this ADR. The Rust and Swift code for #1912 implements §2.1, and it must match
it when it lands. No other flavor needs a change under this rule.

## 3. Consequences

- The text of ADR-0248 §2.1, §2.2, §2.3 and §3, as amended in §2.5, matches the Rust
  and Swift code and the Rust test.
- A lookup of a node whose stored root was released costs O(depth of the surviving
  chain). Every other lookup costs O(1), as before.
- Nodes of one released tree can report different roots, one for each surviving
  chain. The cycle check stays correct. A cycle needs the candidate to be an ancestor
  of the receiver. If a candidate with a parent is an ancestor, both chains pass
  through it and reach the same top, so the roots agree and the case (d) walk runs.
  If the roots differ, no ancestor relation exists, and the transfer proceeds. A
  parentless candidate is an ancestor only when it is the top of the receiver's
  chain, which is the root that the check compares.
- The cycle check of ADR-0248 §2.2 therefore stays correct after a root is released,
  because the walk returns the top of the surviving chain.

## 4. Rejected alternatives

- **Remove the walk, and return no root for a released stored root.** Rejected. The
  cycle check of ADR-0248 §2.2 would have no answer for a node in a surviving chain,
  and it could admit a cycle.
- **A strong root link in Rust and Swift.** Rejected. Each root would own itself
  through a reference cycle, so no tree would be freed (ADR-0247 §2.4).
- **Options (b) and (c) of §2.3.** Rejected for the reasons given there.
