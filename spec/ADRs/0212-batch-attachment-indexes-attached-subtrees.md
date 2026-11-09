# ADR 0212 — Batch attachment indexes attached subtrees, and tree walks catch no read errors

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 18 §6 and §11, chapter 13 §6.1 and §7)
- **Extends:** [ADR-0088](0088-hierarchical-batch-attachment.md) and
  [ADR-0170](0170-tree-walks-report-invalid-factory-output.md). Related:
  #1320, #1434, #1435.

## 1. Context

### 1.1. Batch attachment

ADR-0088 defines the `attachMany` index as the structural root plus its
already-materialized descendants. Chapter 18 §6 added that each successful node
joins the index. It did not mention the descendants of a successful node.

In all five flavors, a successful attach added only the candidate's own key
(#1320). A Python probe at `349ca128` attached the batch `[p, x]`, where `p` had
the materialized child `c` and `x` had the parent key `"c"`. `x` became a
`MissingParent` orphan, although `c` was in the tree at the fixpoint. The same
gap let two nodes share a key: in the batch `[p, c2]`, with `c2` keyed `"c"`
below `"p"`, both `c` and `c2` became children of `p` and `duplicates` was
empty.

The spec also had no rule for a lazy target parent. `AddChild` reads the
children of the parent before it appends the candidate, so a lazy parent runs
its factory. Chapter 18 §6 forbids a factory call only to build the index.

### 1.2. Tree walks

Python `walk`, `walk_expanded` and `find` read children through `iter(node)`.
`_children` caught a `TypeError` from `iter(node)` and fell through to the
`components()` slots. A comment said the fallback served a guarded proxy that
has `__iter__` but rejects `iter()`. No VMx type is such a proxy, and no test
pinned the fallback.

For a `HierarchicalVM`, `iter(node)` reads `children`, which runs the factory.
A factory that returned `None` or raised `TypeError` thus made the node a leaf,
and the caller got no error (#1434). This broke chapter 13 §6.1 and ADR-0170,
which rejects a walk that skips the failing subtree.

ADR-0170 added no conformance ID for the chapter 13 §6.1 rule (#1435).

## 2. Decision

Decided under the owner's delegation: the same rule in every flavor, with the
simplest approach.

### 2.1. Subtree claims

An active candidate claims its own key and the key of every node in its
materialized subtree. The subtree holds the descendants that already-materialized
child lists reach. Reading these keys never runs a children factory.

The claims follow the candidate's own key, in depth-first pre-order, after the
`AlreadyAttached` check. The first claim of a key stays authoritative:

- A descendant key in the index rejects the candidate as
  `DuplicateExistingKey`.
- A descendant key that equals an earlier claim in the batch rejects the
  candidate as `DuplicateBatchKey`. An earlier claim can come from another
  candidate, from another candidate's subtree, or from the same subtree.
- A `keyOf` failure on a descendant rejects the candidate as `SelectorFailed`.
  A parked candidate stays parked, as for its own selectors.

An item that is itself a node of an earlier candidate's materialized subtree
holds that candidate's claim on its key. The item is attached outside the
indexed tree, so it is rejected as `AlreadyAttached` and is not returned in
`duplicates`. This check runs before the `DuplicateBatchKey` check and compares
node identity. Without it, the batch `[p, c]`, where `c` is a child of `p`,
would return the live node `c` in `duplicates`, and the batch `[c, p]` would
reject `c` as `AlreadyAttached`. The rejection now does not depend on the batch
order.

A rejected candidate is returned in `duplicates` (for a key collision), is not
attached, and keeps its subtree. Its claims are not recorded. An accepted
candidate records all of its claims at once.

### 2.2. Subtree indexing

When a candidate attaches, the candidate and every node of its materialized
subtree join the index at once. A later candidate in the same batch can name
any of them as its parent (`HIER-042`).

A candidate whose parent-key chain reaches a node of its own materialized
subtree is in a parent-key cycle. It is rejected as `Cycle`, as for any other
cycle, and is not parked. The cycle check maps each subtree key to the
candidate that claims it.

### 2.3. Lazy target parents

Children that `AddChild` materializes from the factory of a lazy target parent
do not join the index during that batch (`HIER-044`). A candidate whose parent
key names one of them stays unresolved. Under `park`, the next batch indexes
them as materialized descendants and resolves the candidate. A key that a
factory child shares with a candidate is not detected, as for every
unmaterialized subtree.

The rule that the index build runs no factory stays unchanged.

### 2.4. Tree walks

No tree walk catches an error from a children read, in any flavor. Python
`_children` no longer catches a `TypeError` from `iter(node)`. The error
propagates, as in C# and TypeScript. A node whose `iter()` fails is never
walked through its `components()` slots instead. A non-iterable factory result
thus raises `TypeError` from the walks, which is the error a direct `children`
read raises. Changing that error to `ValueError` is a separate hydration
decision.

`UTIL-004` pins the chapter 13 §6.1 rule in all five flavors: the three walks
report invalid factory output, assign no parent, retry the factory on the next
walk, and `find` returns a match that it reaches before the failing node.

## 3. Consequences

- `HIER-042`, `HIER-043`, `HIER-044` and `UTIL-004` join the catalog. It grows
  from 451 to 455 library IDs (460 in total).
- A batch that attaches a prebuilt subtree can name any of its nodes as a
  parent, and it cannot add a second node for a key that the subtree holds.
- A batch that once attached a subtree with a duplicate key now rejects the
  subtree root as a duplicate. A consumer that relied on that gets the
  rejection in `duplicates`.
- An item that is a node of an earlier candidate's subtree is rejected as
  `AlreadyAttached` in either batch order, as before for the order in which it
  comes first. It never appears in `duplicates`, so a consumer that disposes
  or retries `duplicates` never acts on a live node.
- A candidate whose parent key names its own descendant was parked as a
  `MissingParent` orphan that could never resolve. It is now a terminal `Cycle`.
- A Python walk over a custom node whose `__iter__` fails with `TypeError` now
  raises that error instead of yielding the `components()` slots.

## 4. Rejected alternatives

- **Index the factory children after `AddChild`.** The factory children are
  already attached when the batch could read them. A collision with a pending
  candidate could no longer reject either node. Detecting it before the attach
  needs a factory call before `AddChild`, which the index rule forbids.
- **Keep the last claim of a key.** That replaces the authoritative node and
  breaks ADR-0088.
- **Keep the Python `TypeError` fallback for objects that are not a
  `HierarchicalVM`.** No VMx type needs it, and a type check in the walk would
  make the failure rule depend on the node type.
