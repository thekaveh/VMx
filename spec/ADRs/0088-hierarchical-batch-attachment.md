# ADR 0088 — Add key-aware hierarchical batch attachment

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.8.0

## 1. Context

Progressive tree hydration routinely receives children before parents and
overlapping windows with repeated keys. `HierarchicalVM` already owns the
parent, path, message, and cycle invariants, but its single-node mutators force
each consumer to rebuild ordering, deduplication, orphan retention, and partial
failure policy.

Tableau's `mergeCellsIntoCanvas` field implementation required 49 lines for
those mechanics and still allowed one in-batch duplicate to abort the remainder
of a window. These are hierarchy-ingestion invariants rather than Tableau domain
rules.

The proposal's original API omitted the identity and parent lookup mechanism.
`HierarchicalVM` is model-generic and cannot infer either value, so framework
deduplication is impossible without consumer selectors.

## 2. Decision

Add an idiomatic `attachMany` / `AttachMany` / `attach_many` operation in all
five flavors with required `keyOf(node)` and `parentKeyOf(node)` selectors.
Python, TypeScript, Swift, and Rust use a null/`None` parent key for a direct
child of the structural root. C# uses `BatchParentKey<TKey>.Root` so the same
type-safe API supports both reference- and value-type keys.

The receiver resolves its structural root and operates on a key index of that
root plus its already-materialized descendants. It does not force lazy child
factories. The first materialized or active node for a key is authoritative;
same-key inputs are reported as duplicates and never replace it.

Candidate nodes are processed repeatedly in stable input order until no further
parent can be resolved. This yields a fixpoint for child-before-parent chains
and preserves relative input order among siblings. Previously parked nodes are
retried before new input.

The result contains added nodes, duplicates, unresolved orphans, and a typed
rejection entry for every non-added item. Ordinary duplicate, missing-parent,
cycle, already-attached, selector, and underlying attachment failures are data,
not thrown batch failures. A failed underlying attachment is rolled back before
the result is returned so no partial parent/child link remains.

`park` retains only genuine missing-parent items in a structural-root-owned
pending list. A later batch retries them with that call's selectors. `reject`
returns new missing-parent items without retaining them. Parent-key cycles are
terminal rejections, never parked. Root disposal clears pending state.

## 3. Consequences

- `HIER-023..030` cover fixpoint ordering, multiple root items, all duplicate
  scopes, cross-batch parking, reject policy, cycles, structured atomic
  rejection, and disposal.
- Consumers retain domain key selection while VMx owns ingestion invariants.
- Selector functions must be stable and total for every materialized and
  parked node. Selector failures are contained and reported, but inconsistent
  selectors across calls can intentionally reinterpret parked input.
- The materialized-only index preserves lazy loading and makes batch work
  proportional to visible tree state plus the active batch.
- A temporary Tableau pilot at
  `0b53010065f71277d5c3504120e23442a46e30cb` passed its view-model typecheck and
  13 focused tests, but disproved the proposal's “about 10 lines remain”
  estimate. The existing helper is 49 lines (47 nonblank); the direct pilot is
  55 (51 nonblank) because Tableau additionally owns a forest, coordinate
  uniqueness, resolved-ID aliases, and detached-node registration. VMx removes
  generic fixpoint/identity-key mechanics, not those domain adapters.

## 4. Rejected alternatives

A model-specific `id`/`parentId` interface was rejected because VMx models are
language-neutral consumer payloads and existing hierarchies do not implement a
shared identity protocol.

Throwing on the first duplicate or orphan was rejected because it recreates the
window-loss failure this API is intended to prevent.

Silently replacing a same-key node was rejected because it breaks VM identity,
subscriptions, parent links, and lifecycle ownership.
