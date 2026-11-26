# ADR 0255 — A child-transition walk that would wait on itself fails

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 02 §6.1, a new rule; chapter 12 `LIFE-023` and `LIFE-024`; `LIFE-020` is unchanged)
- **Extends:** [ADR-0162](0162-supported-child-transition-helper.md) (adds a refusal to the join rule and keeps its rules). Related: [ADR-0172](0172-one-wait-for-graph-per-flavor.md) (the wait-for graph covers blocking waits only), issues #1962, #750 and #1569.

## 1. Context

The child-transition helper (ADR-0162, spec 02 §6.1) joins a child that is already transient. A join stores a waiter, and the walk waits for the child to settle (`LIFE-020`). A join never calls `construct()` again, so the re-invocation guard of spec 02 §3 does not see it. The wait-for graph of ADR-0172 records blocking waits between threads and keys no edge by view-model, so it does not see a stored join either.

When a walk joins a view-model whose own walk waits back on the walking view-model, the two waits close a loop that no rule refuses. Three shapes do this:

- a leaf whose walk lists itself;
- two leaves whose walks list each other;
- a leaf whose walk lists its own group, which the group's walk starts.

The owner's `construct()` returns without an error. Every view-model on the loop stays `Constructing`, `destruct()` then fails from that state, and only `dispose()` releases them. The issue reproduced this on the Python and TypeScript flavors. The other three flavors were traced from their code, and each joins a transient child the same way.

## 2. Decision

1. **A self-walk is refused.** A walk that lists the view-model whose hook drives it raises the flavor's usage error before it starts or joins any child. It starts no child. The view-model rolls back as for a failing child (spec 02 §2.5).
1. **A cycle is refused before the join.** Each walking view-model records its walk target: the view-model that its walk is starting or joining. It sets the target before the walk starts or joins a child, and clears it when that child settles, when the walk moves on, and when the walk ends by success or failure. Before a walk starts or joins a child, it follows the walk targets from that child. If the chain reaches the walking view-model, the walk raises the usage error and neither starts nor joins the child. Then the walking view-model rolls back, and each view-model that waited on it sees a failed child and rolls back in turn.
1. **The walk targets are one leaf guard per flavor.** Each flavor reads and writes the walk targets under one lock that is never held while a lifecycle lock is taken. Check and set happen under that one lock, so of two walks that close a cycle at the same time, at least one sees the other's target and is refused. The rule holds for every walk entry point: the leaf helper and the container walks (composites, groups and aggregates).
1. **The usage error is the flavor's.** C# `InvalidOperationException`, Python `RuntimeError`, TypeScript `Error`, Swift `ChildTransitionError`, and Rust `VmxError::OwnershipCycle`, which already exists and is not added. The walk-target state is private, so no public or protected member is added and the API listings do not change.
1. **Joins that do not close a cycle are unchanged.** A join of a child that another caller started still waits for it (`LIFE-020`). A diamond, where two walks share a child, still constructs every view-model.
1. **Versions and records.** `spec/VERSION` stays at 3.30.0, because no `spec-v3.30.0` tag exists, as ADR-0214 to ADR-0254 did. No package version changes. Each flavor records the fix in the CHANGELOG under its current unreleased source version.

## 3. Consequences

- A walk that closes a cycle now fails with the usage error, and `construct()` or `destruct()` reports it. Before this rule it returned success and left the view-models transient.
- The check runs once per child that a walk starts or joins, under one short leaf lock. It adds no wait.
- A walk target keeps the view-model it names alive only while the walk runs. Rust stores an identity key, not a reference, so a refused cycle frees both components (`LIFE-024`, drop probe).
- A walk that a flavor cannot start or join because the child is disposed is unaffected (`LIFE-022`).

## 4. Rejected alternatives

- **Key the wait-for graph of ADR-0172 by view-model.** That graph records blocking waits. A join is a stored continuation with no blocked thread, so the graph would need a new edge kind for it. The walk-target chain is the smaller change, and it covers the same cases.
- **Time out a join, or bound the depth of a walk.** A timeout turns a deterministic refusal into a timing-dependent failure and hides the cycle. A depth bound does not detect a cycle; it only stops the walk later.
- **Refuse only a self-walk.** That is the smallest check, but it misses the two-view-model and group cases, which hang the same way.
