# 07 — GroupVM

`GroupVM<VM>` is a container of peers — children with no selection. It is identical
to `CompositeVM<VM>` minus the `Current` slot and minus the selection-related
members and commands.

## Members

```
GroupVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged:
    # IComponentVM members:
    Name, Hint, Type=Group, IsCurrent, IsConstructed, Status,
    ReconstructCommand, can_construct/construct/..., can_select/select/...

    # IList<VM>:
    Add, Remove, Insert, RemoveAt, Clear, Count, indexer, iterator
```

Differences from `CompositeVM<VM>`:

- No `Current` property.
- No `select_component`, `deselect_component`, `can_select_component` —
  children are peers, not selectable from a group-level slot.

The `GroupVM` itself retains `SelectCommand` and `DeselectCommand` from the
`IComponentVM` baseline — they operate on the group's own selection state within
its parent (if any), not on the children. `SelectNextCommand` and
`SelectPreviousCommand` are likewise inherited but their predicates always
return `false`, since a group has no internal navigation slot to advance.

## Children construction orchestration

Identical to `CompositeVM`: `construct()` waits for every child to reach
`Constructed`; `destruct()` waits for every child to reach `Destructed`. The
order in which children are visited is unspecified.

## Builder

The builder accepts:

- `children : () -> Iterable<VM>` (factory, evaluated on `construct()`).

The modeled variant (if needed) follows the same pattern as `CompositeVM<M, VM>`.
In v1.0 only the non-modeled variant ships.

## Auto-construct on add (spec v1.1)

A group built with `AutoConstructOnAdd(true)` MUST automatically call
`construct()` on any child added via `Add` / `Insert` after the group reaches
`Constructed`, completing the child's transition BEFORE the `CollectionChanged`
event fires. The default is `false`.

## Batch updates (spec v1.1)

A group MUST expose a `BatchUpdate()` method returning an `IDisposable` /
context manager. While at least one batch handle is live, mutations MUST NOT
raise individual `CollectionChanged` events. When the last live handle is
disposed, if any mutations occurred a single
`CollectionChanged(action=Reset)` MUST be raised. Nested batches are
ref-counted.

## Conformance

`GRP-001` through `GRP-006` in `12-conformance.md` cover:

- collection-change events on add/remove
- absence of `Current`
- construction waits for all children
- destruction waits for all children
- (v1.1) `AutoConstructOnAdd(true)` auto-constructs children added after the group is `Constructed`
- (v1.1) `BatchUpdate()` suppresses per-mutation events and emits a single `Reset` at completion
