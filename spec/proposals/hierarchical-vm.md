# Proposal — HierarchicalViewModel

**Status:** Proposal (not yet accepted)
**Source:** 2012 VMx predecessor `ToDo/HierarchicalViewModel<*>.cs` (commented-out)
**Captured by:** absorption cycle 11 (ADR-0018 absorption goal)

## 1. Background

The 2012 VMx predecessor's `ToDo/` directory contained a commented-out
research draft for a `HierarchicalViewModel<THierarchicalModel, THierarchicalViewModel>` type, plus its companions `HierarchicalViewModelBase`
and `HierarchicalViewModelContainer`. The intent was a first-class
tree-structured VM whose nodes were themselves containers of the same VM
type — file-system trees, org charts, nested categories.

The draft was never finished. The VMx absorption goal asks us to capture it
as a proposal for future consideration, not to implement it in v2.0.

## 2. Use cases

A HierarchicalViewModel would be valuable when:

- The domain is natively recursive (file directories, comment threads,
  org charts, nested taxonomies).
- The UI needs lazy expansion (load child nodes only when the parent
  expands — see cycle 6's `ExpandableState`).
- The model itself is recursive (`type Folder = { name: string; children: Folder[] }`) and consumers want a 1:1 VM tree without manual recursion.

In v2.0, consumers achieve the same effect by manually nesting
`CompositeVM<M, VM>` instances. The recursion is workable but lacks the
"this is a node in a tree" semantic.

## 3. Proposed shape

```
HierarchicalVM<TModel, TVM>:
    Model      : TModel
    Children   : CompositeVM<TVM>            # peer / sibling collection of same-typed nodes
    Parent     : HierarchicalVM<TModel, TVM>?
    Depth      : int                         # 0 for root, parent.Depth + 1 otherwise
    Path       : Iterable<HierarchicalVM>    # root → … → self
    IsLeaf     : bool                        # Children.Count == 0
    IsRoot     : bool                        # Parent == null
```

The type would integrate with:

- `walk` and `walk_expanded` (cycle 6) for traversal.
- `ExpandableState` (cycle 6) for lazy child loading.
- `SearchableState` (cycle 7) for filtered tree views.
- `ModeledCrudCommands` (cycle 8) for tree-mutation commands.

## 4. Open design questions

1. **Lazy vs eager child loading.** The 2012 draft was eager; modern tree
   UIs usually want lazy. Should `Children` be populated only on first
   access? On `Expand`? Always at construct?
1. **Recursive type parameter.** `HierarchicalVM<TModel, TVM>` where
   `TVM : HierarchicalVM<TModel, TVM>` is the natural shape but introduces
   a recursive generic constraint. Per-flavor ergonomics differ (C#:
   `where TVM : HierarchicalVM<TModel, TVM>`; Python: `T = TypeVar("T", bound=HierarchicalVM)`; TS: `T extends HierarchicalVM<TModel, T>`).
1. **Construction order.** When a parent constructs, must all children
   construct first (per `COMP-004`)? Probably yes, with depth-first
   guarantees similar to `LIFE-013`'s depth-first disposal.
1. **Hub messages.** Should `Parent` changes emit `PropertyChangedMessage`?
   Should the tree publish a separate `TreeStructureChangedMessage` on
   add/remove?
1. **Path semantics.** Stable iterator? Materialized list? Recomputed on
   each access?
1. **Capability integration.** Should `HierarchicalVM` automatically
   implement `IExpandable` (departing from cycle 1's "opt-in only" rule
   for tree-shaped VMs specifically)?

## 5. Status & next steps

This document captures the predecessor's research draft. No ADR is being
written; no code is being added. A future spec cycle (post-v2.0) MAY
revisit this proposal with:

1. A design ADR resolving the open questions above.
1. A new conformance prefix (`HIER-NNN`).
1. Per-flavor implementations.

Until then, consumers needing tree-shaped VMs compose `CompositeVM<M, VM>`
recursively by hand.
