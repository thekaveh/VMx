# 6.2.6. Hierarchical Family

## When To Use It

Use `HierarchicalVM<TModel, TVM>` when the domain is intrinsically recursive:
folders, notebooks, comment threads, taxonomies, or any tree whose nodes need
parent, depth, and path semantics.

This family exists so you do not have to manually recurse a `CompositeVM` and
rebuild tree bookkeeping in every app.

<img src="../../../assets/diagrams/hierarchical-family.svg" alt="Hierarchical Family Map" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/hierarchical-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/hierarchical-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/hierarchical-family.png">PNG</a>
</p>

## Shape And Ownership

A hierarchical node owns:

- its `Model`
- its recursive `Children`
- structural metadata such as `Parent`, `Depth`, `Path`, `IsRoot`, and `IsLeaf`

Children are lazy by default and can be materialized eagerly where the host
needs the whole tree available during construct.

The structural root also owns a small pending set for `attachMany` batch
hydration. Pending nodes are not part of `Children` until their selected parent
is materialized.

## Lifecycle And Messaging

The important differences from manual recursive composites are:

- eager trees construct depth-first across the full subtree
- lazy children do not participate until materialized
- structural mutations publish `TreeStructureChangedMessage`
- cache invalidation publishes property-changed for the children property

The family integrates directly with `walk` and `walk_expanded`.

## Progressive Batch Hydration

Use `attachMany` / `AttachMany` / `attach_many` when windows can overlap or
arrive out of order. The consumer supplies the domain key and parent-key
selectors; VMx owns fixpoint ordering, deduplication, orphan policy, and the
existing parent/path/message invariants.

```ts
const result = canvasRoot.attachMany(windowNodes, {
  keyOf: (node) => node.model.id,
  parentKeyOf: (node) => node.model.parentId, // null means canvasRoot
  onMissingParent: MissingParentPolicy.Park,
});

for (const rejection of result.rejections) {
  diagnostics.record(rejection.item, rejection.reason);
}
```

The root indexes only itself and already-materialized descendants, so batch
attachment never expands a lazy subtree just to search for a parent. It scans
the active nodes to a fixpoint: a parent added later in the input unlocks its
earlier children on the next pass, while sibling order remains the original
input order.

The result separates `added`, `duplicates`, `orphans`, and typed `rejections`.
Same-key nodes never replace an existing VM. `park` retains only genuine
missing-parent items for the next call; `reject` returns them without retaining
them. Cycles, already-attached nodes, and selector/attachment failures are
terminal structured results rather than batch-stopping exceptions. Disposing
the root clears its parked set.

## Tableau Pilot Result

The issue's motivating Tableau helper was piloted in a temporary clone at
`0b53010065f71277d5c3504120e23442a46e30cb`, using the local VMx 3.8 source and
without pushing any Tableau change. The pilot used real `HexNode` instances,
passed the `@tableau/view-model` typecheck, and passed all 8 canvas plus 5
progressive-load tests.

The measurement corrects the proposal's optimistic “about 10 lines remain”
estimate:

| Measurement                              | Existing helper | VMx pilot |
| ---------------------------------------- | --------------- | --------- |
| Total function lines                     | 49              | 55        |
| Nonblank function lines                  | 47              | 51        |
| Direct `attachMany` configuration lines | —               | 4         |

VMx removes the hand-written fixpoint and identity-key replacement logic, but
Tableau still needs domain adaptation for four facts that the generic tree
primitive must not own: its canvas is a forest held by `CompositeVM`, coordinate
uniqueness is independent of cell ID, persisted parent IDs may resolve through
an alias, and fetched documents must become registered/constructed `HexNode`
instances. Those account for roughly 47 nonblank domain/integration lines in
the pilot. Adopting a single synthetic hierarchy root could reduce that adapter,
but would change Tableau's public root/path semantics and was deliberately not
performed in an external repository.

## Cross-Language Surface

| Concept            | C#                                   | Python                               | TypeScript                           | Swift                                   | Rust                              |
| ------------------ | ------------------------------------ | ------------------------------------ | ------------------------------------ | --------------------------------------- | --------------------------------- |
| Core type          | `HierarchicalVM<TModel, TVM>`        | `HierarchicalVM[TModel, TVM>`        | `HierarchicalVM<TModel, TVM>`        | `HierarchicalVM<TModel, TVM>`           | `HierarchicalVm<M>`               |
| Builder            | `HierarchicalVMBuilder<TModel, TVM>` | `HierarchicalVMBuilder[TModel, TVM>` | `HierarchicalVMBuilder<TModel, TVM>` | `HierarchicalVM<TModel, TVM>.builder()` | `HierarchicalVm::builder()`       |
| Eager flag         | `EagerChildren(true)`                | `eager_children(True)`               | `eagerChildren(true)`                | `eagerChildren(true)`                   | `eager_children(true)`            |
| Invalidate subtree | `InvalidateSubtree()`                | `invalidate_subtree()`               | `invalidateSubtree()`                | `invalidateSubtree()`                   | `invalidate_subtree()`            |
| Batch attach       | `AttachMany(...)`                    | `attach_many(...)`                   | `attachMany(...)`                    | `attachMany(...)`                       | `attach_many(...)`                |
| Root parent key    | `BatchParentKey<TKey>.Root`          | `None`                               | `null`                               | `nil`                                   | `None`                            |
| Parked count       | `ParkedAttachCount`                  | `parked_attach_count`                | `parkedAttachCount`                  | `parkedAttachCount`                     | `parked_attach_count()`           |

## Example

The current Notes Workspace examples do **not** subclass `HierarchicalVM` in
any flavor. Each `NotebooksRootVM` owns a flat notebook collection plus
`roots` / `childrenOf` / `walk` projections and republishes
`TreeStructureChangedMessage`, which gives the host tree-shaped state without
making the VM itself a recursive node tree.

Use `HierarchicalVM` when the VM graph should actually be recursive:

These concise examples show the canonical builder path per flavor. C#, Swift,
and TypeScript supply a `TestNode` factory for their concrete recursive node;
Python can build plain `HierarchicalVM` directly and uses `vm_factory(...)` only
when a subclass is required.

=== "C#"

    ```csharp
    var root = HierarchicalVMBuilder<string, TestNode>.Empty
        .Model("root")
        .ChildrenFactory(_ => Array.Empty<TestNode>())
        .Services(hub, dispatcher)
        .VmFactory(ctx => new TestNode(
            ctx.Model, ctx.ChildrenFactory, ctx.Hub, ctx.Dispatcher,
            ctx.Name, ctx.Hint, ctx.EagerChildren))
        .Build();
    ```

=== "Python"

    ```python
    root = (
        HierarchicalVMBuilder()
        .model("root")
        .children_factory(lambda _parent: [])
        .services(hub, dispatcher)
        .build()
    )
    ```

=== "TypeScript"

    ```ts
    const root = new HierarchicalVMBuilder<string, TestNode>()
      .model("root")
      .childrenFactory((_parent) => [])
      .services(hub, dispatcher)
      .vmFactory((ctx) => new TestNode(ctx))
      .build();
    ```

=== "Swift"

    ```swift
    let root = try HierarchicalVM<String, TestNode>.builder()
        .model("root")
        .childrenFactory { _ in [] }
        .services(hub: hub, dispatcher: dispatcher)
        .vmFactory { model, childrenFactory, hub, dispatcher, name, hint, eager in
            TestNode(
                model: model,
                childrenFactory: childrenFactory,
                hub: hub,
                dispatcher: dispatcher,
                name: name,
                hint: hint,
                eagerChildren: eager
            )
        }
        .build()
    ```

That split is the practical rule: use the tree primitive when the tree is real,
not simply because the UI displays indentation.

## Common Pitfalls

- Recursing `CompositeVM` instead of using the tree primitive and then having to
  rebuild `Parent`, `Depth`, and `Path` yourself.
- Expecting lazy children to exist during construct without materializing them.
- Treating cache invalidation as structural mutation. It is a refresh contract,
  not an add/remove event.
- Reparenting a node under itself or its descendants. The contract rejects these
  cycles.
- Using a mutable or call-dependent batch key selector. Parked nodes are retried
  with the next call's selectors, so key semantics must stay stable.
- Treating `park` as a general retry queue. Only missing-parent items park;
  duplicates, cycles, and invalid links are terminal results.

## Related Primitives

- [Composite Family](composite-family.md)
- [State & Reactive Helpers](../state-reactive-helpers.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
