# 13 — Tree utilities

VMx instances form a tree rooted at any `IComponentVM` and reachable through the
children of `CompositeVM`, `GroupVM`, and `AggregateVM`. Two helpers walk that
tree without requiring knowledge of any specific container type.

This module shipped in spec v1.1.

## 1. Members

```
walk(root: IComponentVM) -> Iterable<IComponentVM>
find(root: IComponentVM, predicate: (IComponentVM) -> bool) -> IComponentVM?
walk_expanded(root: IComponentVM) -> Iterable<IComponentVM>      # spec v2.0
```

## 2. `walk`

Yields `root` first, then every descendant in depth-first **pre-order**:

```
walk(root) =
    yield root
    if root is CompositeVM:    for child in root.children: walk(child)
    if root is GroupVM:        for child in root.children: walk(child)
    if root is AggregateVMN:    for slot in root.components: if slot != null: walk(slot)
```

Properties:

- The iteration is lazy in C#, Python, and TypeScript. Consumers MAY stop
  iterating early without traversing the rest of the tree. Swift and Rust
  return a materialized array or `Vec` (§4).
- The order is deterministic given a stable children sequence. For
  `AggregateVMN`, slots are visited in `Component1, Component2, …` order;
  empty slots (`null` / `None`) are skipped.
- A leaf `ComponentVM` yields exactly itself.

`walk` does NOT trigger any lifecycle transition; it is a pure read.

## 3. `find`

Returns the first node for which `predicate(node)` is truthy when iterating in
`walk` order, or `null` / `None` if no node matches.

Properties:

- `find(root, _ => true)` returns `root`.
- `find` SHOULD short-circuit on the first match (no traversal of the remaining
  tree).
- The predicate is invoked at most once per visited node.

## 4. Idiomatic surface

| Flavor     | Module          | Walk / WalkExpanded return                   | Find return                      |
| ---------- | --------------- | -------------------------------------------- | -------------------------------- |
| C#         | `VMx.Tree`      | `IEnumerable<IComponentVM>` (lazy)           | `IComponentVM?`                  |
| Python     | `vmx.tree`      | `Iterator[ComponentVMProto]` (generator)     | `ComponentVMProto \| None`       |
| TypeScript | `@thekaveh/vmx` | `Iterable<ComponentVMBase>` (generator)      | `ComponentVMBase \| null`        |
| Swift      | `VMx`           | `throws -> [ComponentVMBase]` (materialized) | `throws -> ComponentVMBase?`     |
| Rust       | `vmx`           | `VmxResult<Vec<TreeNodeRef>>` (materialized) | `VmxResult<Option<TreeNodeRef>>` |

Rust walks any `TreeNode` root. `TreeNode::try_children_nodes` lists a node's
children as type-erased `TreeNodeRef` handles, so a walk crosses containers
whose children have different types. `CompositeVm`, `ModeledCompositeVm`, and
`GroupVm` list their children, `AggregateVm1` to `AggregateVm6` list their
present components in slot order, and `HierarchicalVm` lists its children.
`TreeNodeRef::downcast` returns the concrete node (ADR-0207).

`walk_expanded` (spec v2.0) shares the same return shape as `walk` per flavor.
Swift returns materialized `[ComponentVMBase]` arrays rather than lazy sequences
(idiomatic per ADR-0059 §2.5; `find` still short-circuits, and the result is
identical for the finite trees this API supports).

## 5. Expand-aware traversal (spec v2.0)

`walk_expanded` is a variant of `walk` that only descends into children whose
parent reports as expanded (per ADR-0015 and the `IExpandable` capability
in `14-capabilities.md`):

```
walk_expanded(root) =
    yield root
    if root is IExpandable AND root.IsExpanded == false:
        return                  # do not descend
    if root is CompositeVM:     for child in root.children: walk_expanded(child)
    if root is GroupVM:         for child in root.children: walk_expanded(child)
    if root is AggregateVMN:    for slot in root.components: if slot != null: walk_expanded(slot)
```

Properties:

- `walk_expanded` descends into the **same container set** as `walk` — the
  children of a `CompositeVM` / `GroupVM` **and** the non-null slots of an
  `AggregateVMN` (in `Component1, Component2, …` order) — gated only by the
  `IExpandable` check. The reference implementations share one descent helper
  between `walk` and `walk_expanded`, so an aggregate-rooted (or
  aggregate-containing) tree is traversed identically except for the expansion
  gate. An earlier revision of this pseudocode wrote "`if root has children`",
  which read as composites/groups only; the aggregate-slot descent the
  implementations have always performed is now explicit (clarified in v3 via
  ADR-0051).
- A node that does NOT implement `IExpandable` is treated as always-expanded
  (i.e., the traversal descends as `walk` would).
- A node that DOES implement `IExpandable` gates descent on `IsExpanded`:
  collapsed nodes contribute themselves to the iteration but contribute none
  of their descendants.
- Like `walk`, the iteration is deterministic and triggers no lifecycle
  transitions. It is lazy in C#, Python, and TypeScript; Swift and Rust return
  a materialized array or `Vec`.

This helper enables tree-view consumers to render only the visible portion
of the VM tree without writing their own descent logic.

## 6. Integration with `HierarchicalVM`

When applied to a `HierarchicalVM<TModel, TVM>` instance:

- `walk(node)` yields depth-first descendants including the root. Order is
  `parent → children[0] → children[0].children[0] → … → children[1] → …`.
- `walk_expanded(node)` honors the lazy boundary: an `ExpandableState`-composed
  node whose `IsExpanded == false` does NOT yield its children. Useful for
  tree-view rendering that should only show expanded branches.

Rust composes the state with `HierarchicalVm::compose_expansion`, and
`TreeNode::expandable` then returns it (ADR-0207).

See [chapter 18](18-hierarchical-vm.md) for HierarchicalVM details.

### 6.1. Invalid factory output

A walk can reach a node whose lazy children factory returns invalid output
(chapter 18 §4). Then `walk`, `walk_expanded`, and `find` report the
hydration error to the caller as the flavor's ordinary recoverable error. They
never stop the process (ADR-0170):

| Flavor     | Failure surface                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| C#         | The `Children` error (`InvalidOperationException`) propagates when the lazy sequence reaches the node. |
| Python     | The `children` error (`ValueError`) propagates when the generator reaches the node.                    |
| TypeScript | The `children` error (`Error`) propagates when the generator reaches the node.                         |
| Swift      | `walk`, `walkExpanded`, and `find` throw `HierarchyError.invalidFactoryOutput`.                        |
| Rust       | `walk`, `walk_expanded`, and `find` return the `try_children` error (`VmxError::InvalidArgument`).     |

Swift and Rust read the fallible `tryChildren()` / `try_children()` accessor
for this. Rust reads it through `TreeNode::try_children_nodes`, which returns
no children by default. The rejected node keeps no children cache, so a later
walk runs the factory again. A walk reads a node's children only when it
descends into that node. `find` therefore returns a match that it reaches
before the failing node, and `walk_expanded` never reads the children of a
collapsed node.

## 7. Conformance

`UTIL-001` through `UTIL-003` and `EXP-001` through `EXP-005` in
`12-conformance.md` cover:

- `walk` yields root, then every descendant, in DFS pre-order
- `walk` skips empty aggregate slots
- `find` returns the first matching node and short-circuits
- `walk_expanded` walks the tree but stops descent at every node whose
  `IExpandable.IsExpanded` is `false` (collapsed nodes contribute themselves
  but none of their descendants)
- `ExpandableState` provides default values, `Expand`/`Collapse`/`Toggle`
  operations, and an `IsExpandedChanged` observable, idempotent under repeat
  Expand/Collapse
