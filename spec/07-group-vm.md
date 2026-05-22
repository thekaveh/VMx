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
- No `SelectNextCommand`, `SelectPreviousCommand` (children are peers, not navigable).
- No `select_component`, `deselect_component`, `can_select_component`.

The `GroupVM` itself retains `SelectCommand` and `DeselectCommand` from the `IComponentVM`
baseline — they operate on the group's own selection state within its parent (if any), not
on the children. It is only navigation *within* the group that is absent.

## Children construction orchestration

Identical to `CompositeVM`: `construct()` waits for every child to reach
`Constructed`; `destruct()` waits for every child to reach `Destructed`. Construct
and destruct proceed in parallel across children.

## Builder

The builder accepts:

- `children : () -> Iterable<VM>` (factory, evaluated on `construct()`).

The modeled variant (if needed) follows the same pattern as `CompositeVM<M, VM>`.
In v1.0 only the non-modeled variant ships.

## Conformance

`GRP-001` through `GRP-004` in `12-conformance.md` cover:

- collection-change events on add/remove
- absence of `Current`
- construction waits for all children
- destruction waits for all children
