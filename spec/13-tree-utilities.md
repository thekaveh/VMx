# 13 — Tree utilities

VMx instances form a tree rooted at any `IComponentVM` and reachable through the
children of `CompositeVM`, `GroupVM`, and `AggregateVM`. Two helpers walk that
tree without requiring knowledge of any specific container type.

This module shipped in spec v1.1.

## Members

```
walk(root: IComponentVM) -> Iterable<IComponentVM>
find(root: IComponentVM, predicate: (IComponentVM) -> bool) -> IComponentVM?
```

## `walk`

Yields `root` first, then every descendant in depth-first **pre-order**:

```
walk(root) =
    yield root
    if root is CompositeVM:    for child in root.children: walk(child)
    if root is GroupVM:        for child in root.children: walk(child)
    if root is AggregateVMN:    for slot in root.components: if slot != null: walk(slot)
```

Properties:

- The iteration is lazy. Consumers MAY stop iterating early without traversing
  the rest of the tree.
- The order is deterministic given a stable children sequence. For
  `AggregateVMN`, slots are visited in `Component1, Component2, …` order;
  empty slots (`null` / `None`) are skipped.
- A leaf `ComponentVM` yields exactly itself.

`walk` does NOT trigger any lifecycle transition; it is a pure read.

## `find`

Returns the first node for which `predicate(node)` is truthy when iterating in
`walk` order, or `null` / `None` if no node matches.

Properties:

- `find(root, _ => true)` returns `root`.
- `find` SHOULD short-circuit on the first match (no traversal of the remaining
  tree).
- The predicate is invoked at most once per visited node.

## Idiomatic surface

| Flavor     | Module     | Walk return                          | Find return            |
| ---------- | ---------- | ------------------------------------ | ---------------------- |
| C#         | `VMx.Tree` | `IEnumerable<IComponentVM>` (lazy)   | `IComponentVM?`        |
| Python     | `vmx.tree` | `Iterator[IComponentVM]` (generator) | `IComponentVM \| None` |
| TypeScript | `vmx/tree` | `Iterable<IComponentVM>` (generator) | `IComponentVM \| null` |

## Conformance

`UTIL-001` through `UTIL-003` in `12-conformance.md` cover:

- `walk` yields root, then every descendant, in DFS pre-order
- `walk` skips empty aggregate slots
- `find` returns the first matching node and short-circuits
