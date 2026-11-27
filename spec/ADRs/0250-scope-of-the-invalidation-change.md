# ADR 0250 — Scope of the invalidation change and correction of ADR-0247 section 1

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (no chapter change, no conformance ID change and no library behavior change in this pull request)
- **Related:** [ADR-0247](0247-hierarchy-root-pointer.md) section 1 (corrected in §2.1 below). Also [ADR-0247](0247-hierarchy-root-pointer.md) §2.3 and §2.5, which [ADR-0249](0249-released-tree-root-walks-parent-links.md) §2.6 corrected, and [ADR-0248](0248-attach-cycle-check-by-tree-root.md), #1912.

## 1. Context

ADR-0247 section 1 describes the scope of issue #1912. Two of its statements about that scope do not match the issue body. This ADR corrects them. It also decides the scope question that the correction raises: whether the Python part of the iterative subtree invalidation stays in the change.

### 1.1 What the issue says

The Scope section of issue #1912 reads, in full:

> In: `walk`, `walk_expanded`, `find`, `depth`, Rust `path` and path-cache invalidation in each flavor that recurses. Out: the construct, destruct and dispose walks. Their behavior on deep chains, including eager construction, is not measured. Also out: Python `invalidate_subtree`, which recurses through `_invalidate_subtree_nodes` (traced, not measured).

The Summary of the issue gives the requested outcome as "walks, `depth` and path-cache invalidation use loops, so tree depth is limited only by memory."

The body does not name `invalidateSubtree` in camelCase. It names Python `invalidate_subtree` and puts it out of scope. The attach cycle check appears in the body only in the evidence table. That table names the Python check at `langs/python/src/vmx/hierarchical/hierarchical_vm.py` L352-L358 in commit df169610, where each `_attach_child` reads the receiver's cached `path` for the cycle check. The Summary and the Scope do not ask for the attach cycle check.

### 1.2 What ADR-0247 section 1 says

ADR-0247 section 1 says that issue #1912 "asks that tree walks, `depth`, path-cache invalidation and the attach cycle check cost no stack frame per tree level, and no ancestor walk per attach." Its item 1 says that "`invalidateSubtree` still recurses once per level in every flavor." Both statements read the issue as broader than its Scope.

ADR-0247 §2.3 (D3) includes Python `_invalidate_subtree_nodes` in the change. The issue's Scope excludes it by name. Section 2.2 of this ADR decides that difference.

### 1.3 Code on origin/develop

- Python `invalidate_subtree` (`langs/python/src/vmx/hierarchical/hierarchical_vm.py` L679-L687) calls `_invalidate_subtree_nodes`. That function uses an explicit stack (L689-L704). It was merged in commit eeff14ab, pull request #2228.
- Before eeff14ab, in commit 28f91cd6, the same function recursed once per level. Its self-call is at L671 of the same file.
- ADR-0247 section 1 measured the recursion on origin/develop 3b027405, before pull request #2228. There `invalidateSubtree` failed in Python at 974 to 1036 levels, and the default recursion limit is 1000. This ADR does not repeat that measurement.
- The other flavors have their iterative invalidation on origin/develop. TypeScript `invalidateSubtree` is at `langs/typescript/src/hierarchical/hierarchicalVm.ts` L601, and its explicit stack is at L606 (commit 28f91cd6, pull request #2222). C# `InvalidateSubtree` and `DropSubtree` are at `langs/csharp/src/VMx/Hierarchical/HierarchicalVM.cs` L589-L596 (commit 0aca93e3, pull request #2223). Rust `invalidate_subtree_from_live_ancestor` is at `langs/rust/src/hierarchical.rs` L986, and its explicit stack is at L991 (commit c938339c, pull request #2224).
- Swift `invalidateMaterializedSubtree` is iterative on origin/develop (`langs/swift/Sources/VMx/Hierarchical/HierarchicalVM.swift`, from L740). Its iterative form landed with pull request #2225 (commit 7d445367), which is merged. This section described the state before that merge.

## 2. Decision

### 2.1 Correction of ADR-0247 section 1

The issue body is the source for the scope. ADR-0247 section 1 is corrected as follows.

(a) The issue names path-cache invalidation as in scope. It names Python `invalidate_subtree` as out of scope. It does not name `invalidateSubtree` in camelCase. The sentence "`invalidateSubtree` still recurses once per level in every flavor" describes the code before the fix. It does not describe the scope of the issue.

(b) The attach cycle check is not in the Summary, the requested outcome or the Scope of the issue. The issue names the Python attach check only in its evidence table, at df169610 L352-L358. The requested outcome does not ask for the attach check. On origin/develop the same check starts in `_attach_child` (defined at L347), which calls `_reject_reparent_cycle` at L359. The cases of that check are at L412, L414, L416 and L418 of the same file.

The decision text of ADR-0247 is not changed. Only its section 1 reading of the issue is corrected here.

### 2.2 The Python part of the invalidation change

The iterative `invalidateSubtree` of ADR-0247 §2.3 (D3) stays in the change in every flavor, including Python, as merged in pull request #2228 (commit eeff14ab). Two reasons apply.

- The recursion fails in Python at the default recursion limit of 1000. ADR-0247 §1 measured failures at 974 to 1036 levels on origin/develop 3b027405. The code before the fix recursed once per level (commit 28f91cd6, `hierarchical_vm.py` L666-L673).
- The Summary of the issue states the goal that tree depth is limited only by memory. The Scope excludes Python `invalidate_subtree` and marks that exclusion as "traced, not measured". Keeping the recursion would leave a depth limit of about 1000 levels on invalidation. ADR-0247 §1 has since measured that limit.

The Python part stays (§2.3). Section 2.3 names the commit that would remove it.

### 2.3 Decision: the Python part stays

Status: decided 2026-11-27 under the owner's delegated design rule (cross-flavor uniform and simplest). The Python part of the invalidation change stays. The four other flavors use an explicit stack, and removing the Python part would bring back the recursion limit that §2.2 names. The owner may still reverse this with the commit named below. The commit that would remove it is eeff14ab (pull request #2228). That commit is a combined change. It adds the Python root pointer of ADR-0248 R3 and the iterative invalidation. Reverting the whole commit would also remove the root pointer and the cycle check that reads it, so it is not a Python-only removal.

A Python-only removal swaps the explicit stack in `_invalidate_subtree_nodes` (`langs/python/src/vmx/hierarchical/hierarchical_vm.py` L689-L704) with the recursive form that commit 28f91cd6 had at L666-L673. It keeps the root pointer. The answer to this owner item affects only the Python function. The other four flavors do not depend on it.

### 2.4 Scope

This ADR adds no public API, no error text, no conformance ID, no spec chapter change and no version bump, and it changes no library code. Its changes under `spec/` are this file, the registry row of this ADR, the Status line and registry cell of ADR-0247 (the back-link to §2.1), and one sentence in section 39 of `spec/HISTORY.md` that names this ADR. ADR-0248 and ADR-0249 are unchanged.

## 3. Consequences

- ADR-0247 section 1 is read with the correction in §2.1. Its decision text is unchanged.
- The Python invalidation is iterative on origin/develop and stays iterative unless the owner decides otherwise (§2.3). No recursion limit applies to Python `invalidate_subtree` in that case.
- The issue's written Scope still excludes Python `invalidate_subtree`. The pull request for this ADR states the difference, so the reviewer can see it.
- Swift's iterative invalidation landed with pull request #2225 (commit 7d445367), which is merged. `invalidateMaterializedSubtree` is iterative on origin/develop.

## 4. Rejected alternatives

- **Remove the Python invalidation change now, to match the issue's Scope.** Not chosen. It brings back the recursion limit that §2.2 names. The owner can still take that path, using the commit named in §2.3.
- **Edit ADR-0247 section 1 in place.** Not chosen. The ADR-0249 precedent corrects an accepted ADR with a new ADR and a Status back-link, as ADR-0249 §2.6 did for ADR-0247 §2.3 and §2.5.
