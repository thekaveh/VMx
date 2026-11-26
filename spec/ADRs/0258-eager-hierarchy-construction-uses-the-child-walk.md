# ADR 0258 — Eager hierarchy construction uses the child walk

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 18 §3, a new paragraph; chapter 18 §11, a new row; chapter 12 `HIER-045`)
- **Extends:** [ADR-0189](0189-disposed-children-leave-current-and-container-walks.md) (adds eager `HierarchicalVM` construction to the walk rules and keeps them). Related: [ADR-0156](0156-hierarchy-eager-is-per-node-and-access-does-not-construct.md) (eager mode is per node), [ADR-0162](0162-supported-child-transition-helper.md) (the child-transition helper), [ADR-0255](0255-child-transition-walks-refuse-a-wait-cycle.md) (the walk refuses a wait cycle), issue #1919.

## 1. Context

Eager construction of a `HierarchicalVM` (chapter 18 §3) constructs each direct child before the node reaches `Constructed`. Chapter 18 §3 did not say which rules apply to those children. The child-transition helper of chapter 02 §6.1 (ADR-0162) has these rules for a leaf view-model: it skips a `Disposed` child, joins a child that is already transient, stops when its owner is disposed, waits for a deferred child, and rolls its owner back when a child fails.

C#, Python, TypeScript and Rust route eager construction through that helper, so they follow those rules. Swift's eager construction was a hand-written loop over `construct()`. For a disposed child it threw "Cannot construct from state Disposed.", so every later `construct()` and `reconstruct()` of the parent failed (issue #1919). The loop also threw on a child that was already `Constructing`. It did not stop when a child hook disposed the parent. It reported the parent `Constructed` while a child whose construct was still in flight stayed `Constructing`. When that child later failed, the parent stayed `Constructed` over a `Destructed` child.

## 2. Decision

1. **Eager construction uses the walk.** Eager construction of a `HierarchicalVM` constructs its direct children through the child-transition walk of chapter 02 §6.1, and the walk applies its rules to them. Chapter 18 §3 states those rules.
1. **A disposed child is skipped.** The walk skips a `Disposed` child and calls no lifecycle operation on it (ADR-0189, `HIER-045`).
1. **An in-flight child is joined and waited for.** A child that is already `Constructing` is joined, not started again (`LIFE-020`). The node stays `Constructing` until that child settles, and it reaches `Constructed` only after every child has (chapter 18 §3).
1. **A failed child rolls the node back.** A child that fails rolls the node back to its prior settled status. This holds for a child that failed after it deferred its construct: the node that waited for it rolls back as well, and both end `Destructed` (chapter 02 §2.5 and §6.1).
1. **A disposed owner stops the walk.** When a child hook disposes the node, the walk starts no later child (`LIFE-015`).
1. **Errors keep their category.** `tryChildren()` rejects a factory that lists its own node, and a child that already has a parent, as `HierarchyError.invalidFactoryOutput`, as before. For the root this happens before the walk starts. For an inner node it happens inside that node's construct, after the outer walk has started, and the outer walk rolls back with the same error. Eager construction adds no error type, and these shapes do not reach the walk's own `ChildTransitionError`, because `tryChildren()` rejects them first.
1. **Versions and records.** `spec/VERSION` stays at 3.30.0, because no `spec-v3.30.0` tag exists, as ADR-0214 to ADR-0257 did. No public member changes, so the API listings do not change. Each changed flavor records its change in its CHANGELOG under its current unreleased source version.

## 3. Consequences

- Swift's eager construction changes in the ways §2 lists. The other four flavors already follow these rules. Their `HIER-045` tests pass with no change to their source.
- A parent with a child whose construct defers stays `Constructing` until that child settles, and it rolls back if that child fails. In Swift a `HierarchicalVM` node is never a background node, so this happens only when a child's own construct hook defers.
- A structural factory error is reported where and as it was before.

## 4. Rejected alternatives

- **Skip only `Disposed` in the Swift loop.** That fixes the reported throw. It leaves the join, wait, stop and rollback rules of the walk unmatched, so Swift would still differ from the other four flavors.
- **Keep the loop and document it as the rule.** The other four flavors implement and test the walk rules. The spec would then describe a behavior those flavors do not have.
- **Refuse a deferred child at construct time.** A deferred child is a state the walk already handles. Refusing it would break the wait rule of chapter 02 §6.1 for this node.
