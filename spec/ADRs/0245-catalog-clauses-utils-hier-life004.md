# ADR 0245 — Catalog clauses for UTIL-002 and HIER-012 match the spec, and LIFE-004 asserts Disposed in every flavor

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapters 08 and 13; `UTIL-002`, `HIER-012`, `LIFE-004`; no library behavior change)
- **Clarifies:** [ADR-0051](0051-v3-tree-collections-capability-and-spec-organization-gaps.md) (the tree walk rules that `UTIL-002` and `HIER-012` state). Related: [ADR-0028](0028-hierarchical-vm.md) §3.6, #1808, #1795, #2071.

## 1. Context

Issue #1808 asks that each catalog clause is asserted by a test in every flavor.
PR #2071 merged most of the assertions. Three items remained.

- **`UTIL-002`.** The catalog Given asks for an `AggregateVM3` whose middle slot
  is null. Spec chapter 08 §1 fills each slot from its factory at construct time,
  and chapter 08 treats an empty slot in an existing aggregate as an invalid
  state. No public API builds the Given. The Python test wrote the private field
  `agg._component2 = None`. The C#, TypeScript, Swift and Rust tests check the
  pre-construct state instead, where every slot is empty.
- **`HIER-012`.** The catalog Given is a three-level tree. Spec chapter 13 always
  descends a node that does not implement `IExpandable`, so `walk_expanded`
  also yields the grandchildren. The catalog Then names only the root and its
  direct children. The C#, TypeScript, Swift and Rust tests build a two-level
  tree. The Python test builds three levels and asserts the grandchild.
- **`LIFE-004`.** The catalog Then asserts a `ConstructionStatusChangedMessage`
  with `Status = Disposed` on the hub, for all four listed states. The Python,
  C#, Swift and Rust tests assert it when dispose runs from `Constructing` and
  from `Destructing`. The TypeScript test that disposes from a status observer
  covers those two states, but it does not assert the message.

## 2. Decision

### 2.1 `UTIL-002` catalog text: the pre-construct state

The Given is an `AggregateVM3` built with three component factories and not yet
constructed. The Then is the sequence `[agg]`, with no entry for an empty slot.
After `construct()`, the sequence is
`[agg, agg.Component1, agg.Component2, agg.Component3]`. Public builders and
lifecycle methods reach this state. The Python test sets up this state and no
longer writes `_component2`.

### 2.2 `HIER-012` catalog text: a two-level tree

The Given is a two-level tree: a root with leaf children, where the root has
`ExpandableState` composed. The Then is unchanged. The Python test keeps its
three-level tree and its grandchild assertion, as issue #1808 step 13 directs.
Chapter 13 always descends a node that is not `IExpandable`, so the grandchild
is yielded, and the Python test asserts it. The catalog Then does not name the
grandchild, so the Python test checks more than the catalog states. The other
four flavors check the two-level tree only, so `HIER-012` checks chapter 13's
descent rule in Python alone.

### 2.3 `LIFE-004`: one assertion for all five flavors

The `LIFE-004` catalog text is unchanged. Every flavor asserts the `Disposed`
hub message for dispose from `Constructing` and from `Destructing`. The
new TypeScript test in the `LIFE-004` block disposes inside the construct or
destruct hook, as the Python test does, and asserts exactly one `Disposed`
message. The issue named only
Python, Swift and Rust. The catalog's second clause covers all four states, so
the same assertion applies to TypeScript.

### 2.4 Scope and numbering

No conformance ID is added or removed, so every catalog count is unchanged. No
library code changes, so no CHANGELOG entry and no version bump are needed.
ADR-0244 is held for open pull request #2194, which has no registry row here.
ADR-0245 is the next free number.

## 3. Consequences

- The `UTIL-002` and `HIER-012` Givens name only states that public APIs build.
  Their Thens match chapters 08 and 13.
- The Python `HIER-012` test asserts a grandchild that the catalog Then does not
  name. Adding the grandchild to the Then would need the same assertion in the
  other four flavors. This ADR does not change the Then, so that choice stays
  with the owner.
- The pre-construct leg of `UTIL-002` cannot separate a walk that stops at the
  first empty slot from one that skips it, because both yield `[agg]`. The
  removed middle-slot test made that separation. No public API builds a middle
  empty slot, so this gap stays open. Restoring the check needs a public way to
  build an empty middle slot, which chapter 08 does not describe. This ADR does
  not add one.
- Each changed or new test was shown to fail under a named library mutation.
  Each mutation was reverted, and the library diff was empty before the commit.
  - TypeScript `LIFE-004`, new test: `_setStatus` skips the `Disposed` message
    when the prior status is `Constructing`. The test fails with
    `expected [] to have a length of 1`.
  - Python `UTIL-002`: `walk` yields an entry for an empty slot. Aggregate
    `components()` keeps `None` entries, the walk filter is removed, and the
    child iterator ends on a private sentinel, so `None` is yielded. The test
    fails at the pre-construct assertion with
    `AttributeError: 'NoneType' object has no attribute 'name'`.
  - Python `HIER-012`, collapsed boundary: `walk_expanded` ignores `IsExpanded`.
    The collapsed root yields its children, and the test fails with
    `assert [...] == [root]` (left side has 3 more items).
  - Python `HIER-012`, grandchild: `_is_expanded_or_not_expandable` returns
    `isinstance(node, IExpandable) and node.is_expanded`, so a non-expandable
    child is not descended. The three-level test fails at the grandchild
    assertion with `AssertionError: assert {'child-a', 'child-b', 'root'} == {...}`.

## 4. Rejected alternatives

- **Keep the middle-slot Given and add a public way to empty a slot.** Rejected.
  Chapter 08 calls an empty slot invalid, so a test-only API would add surface
  that the spec does not describe.
- **Keep the three-level `HIER-012` Given and add the grandchild to the Then.**
  Rejected. The Then would then depend on the arity of the tree, and every
  flavor other than Python would need a new clause. The two-level tree matches
  the other four flavors.
- **Limit the `LIFE-004` assertion to Python, Swift and Rust, as the issue
  named.** Rejected. The second catalog clause covers all four states, so the
  five flavors must meet the same clause.
