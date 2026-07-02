# Hierarchical Family

## When To Use It

Use `HierarchicalVM<TModel, TVM>` when the domain is intrinsically recursive:
folders, notebooks, comment threads, taxonomies, or any tree whose nodes need
parent, depth, and path semantics.

This family exists so you do not have to manually recurse a `CompositeVM` and
rebuild tree bookkeeping in every app.

## Shape And Ownership

A hierarchical node owns:

- its `Model`
- its recursive `Children`
- structural metadata such as `Parent`, `Depth`, `Path`, `IsRoot`, and `IsLeaf`

Children are lazy by default and can be materialized eagerly where the host
needs the whole tree available during construct.

## Lifecycle And Messaging

The important differences from manual recursive composites are:

- eager trees construct depth-first across the full subtree
- lazy children do not participate until materialized
- structural mutations publish `TreeStructureChangedMessage`
- cache invalidation publishes property-changed for the children property

The family integrates directly with `walk` and `walk_expanded`.

## Cross-Language Surface

| Concept            | C#                                   | Python                               | TypeScript                           | Swift                         |
| ------------------ | ------------------------------------ | ------------------------------------ | ------------------------------------ | ----------------------------- |
| Core type          | `HierarchicalVM<TModel, TVM>`        | `HierarchicalVM[TModel, TVM]`        | `HierarchicalVM<TModel, TVM>`        | `HierarchicalVM<TModel, TVM>` |
| Builder            | `HierarchicalVMBuilder<TModel, TVM>` | `HierarchicalVMBuilder[TModel, TVM]` | `HierarchicalVMBuilder<TModel, TVM>` | constructor surface           |
| Eager flag         | `EagerChildren(true)`                | `eager_children(True)`               | `eagerChildren(true)`                | `eagerChildren: true`         |
| Invalidate subtree | `InvalidateSubtree()`                | `invalidate_subtree()`               | `invalidateSubtree()`                | `invalidateSubtree()`         |

## Example

The Notes Workspace feature tables point to concrete tree implementations:

- C#: notebooks tree in `ViewModels/NotebooksRootVM.cs`
- Python: notebooks tree in `viewmodels/notebooks_root_vm.py`
- TypeScript: notebooks tree in `viewmodels/notebooksRootVM.ts`
- Swift: the flagship keeps a flat notebook list and mirrors the structural
  notifications contract without using `HierarchicalVM` directly

That split is a good reminder: choose the tree primitive when the tree is real,
not simply because the UI displays indentation.

## Common Pitfalls

- Recursing `CompositeVM` instead of using the tree primitive and then having to
  rebuild `Parent`, `Depth`, and `Path` yourself.
- Expecting lazy children to exist during construct without materializing them.
- Treating cache invalidation as structural mutation. It is a refresh contract,
  not an add/remove event.
- Reparenting a node under itself or its descendants. The contract rejects these
  cycles.

## Related Primitives

- [Composite Family](composite-family.md)
- [State & Reactive Helpers](../state-reactive-helpers.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
