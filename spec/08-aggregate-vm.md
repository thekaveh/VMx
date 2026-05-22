# 08 — AggregateVM

`AggregateVM<VM1..VMN>` is a fixed-arity tuple of heterogeneous component VMs. VMx
v1.0 ships arities 1 through 5 (`AggregateVM1` through `AggregateVM5` — see
ADR-0007).

## Members (arity N)

```
AggregateVMN<VM1..VMN> : IComponentVM:
    # IComponentVM members:
    Name, Hint, Type=Aggregate, IsCurrent, IsConstructed, Status,
    SelectCommand, DeselectCommand, SelectNextCommand, SelectPreviousCommand, ReconstructCommand,
    can_construct/construct/..., can_select/select/...

    # Aggregate-specific:
    Component1 : VM1
    Component2 : VM2   # only on arity ≥ 2
    Component3 : VM3   # only on arity ≥ 3
    Component4 : VM4   # only on arity ≥ 4
    Component5 : VM5   # only on arity ≥ 5
```

A child slot is populated by invoking a lazy factory at construct time. The factory
is provided via the builder:

```
AggregateVM3.Builder()
    .Name("...").Hint("...")
    .Services(hub, dispatcher)
    .Component1(() => MyComponentVM1.Build(...))
    .Component2(() => MyComponentVM2.Build(...))
    .Component3(() => MyComponentVM3.Build(...))
    .Build()
```

## Construction

`construct()`:

1. Invokes every component factory in parallel, populating the `ComponentN` slots.
1. Subscribes to each child's `ConstructionStatusChangedMessage` on the hub.
1. Waits for every child to reach `Constructed`.
1. Transitions to `Constructed` and emits its own status message.

On each successful slot population, the aggregate raises
`PropertyChangedMessage("ComponentN")`.

## Destruction

`destruct()`:

1. Invokes `destruct()` on each `ComponentN` slot in parallel.
1. Waits for every child to reach `Destructed`.
1. Transitions to `Destructed`.

## Selection

The aggregate itself can be selected (via its parent's `Current`), and like any other
`IComponentVM` it exposes `SelectCommand`, `DeselectCommand`, `SelectNextCommand`, and
`SelectPreviousCommand` for navigation within its own parent. The individual `ComponentN`
slots, however, are not selectable — they are the aggregate's fixed structure, not
navigable peers, so there are no `select_component` / `deselect_component` methods.

## Arity rationale

ADR-0007 documents why arities 1–5 are the supported range. For more than 5
heterogeneous children, prefer `CompositeVM<VM>` or `GroupVM<VM>` with a
heterogeneous-base-type `VM`, or compose multiple aggregates.

## Conformance

`AGG-001` through `AGG-005` in `12-conformance.md` cover:

- arity-1 component factory invoked on construct
- arity-2 both components reach Constructed in parallel
- arity-5 all five components reach Constructed before parent
- ComponentN property change fires on construct
- destruction waits for all children
