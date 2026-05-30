# 08 — AggregateVM

`AggregateVM<VM1..VMN>` is a fixed-arity tuple of heterogeneous component VMs. VMx
ships arities 1 through 6 (`AggregateVM1` through `AggregateVM6` — see ADR-0007 and ADR-0034).

## 1. Members (arity N)

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
    Component6 : VM6   # only on arity ≥ 6
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

## 2. Construction

`construct()`:

1. Invokes every component factory, populating the `ComponentN` slots.
1. Calls `construct()` on each child; each call returns once that child has
   reached `Constructed` (per ADR-0008's synchronous lifecycle contract).
1. Transitions to `Constructed` and emits its own status message.

An asynchronous flavor MAY observe the children's
`ConstructionStatusChangedMessage(Constructed)` on the hub instead; the
synchronous default is a strict subset of that behavior.

The order in which the slots are populated and constructed is unspecified.
The reference implementations in all three flavors drive them sequentially
(mirroring `CompositeVM` / `GroupVM`; see chapter 06).

On each successful slot population, the aggregate raises
`PropertyChangedMessage("ComponentN")`.

## 3. Destruction

`destruct()`:

1. Invokes `destruct()` on each `ComponentN` slot.
1. Waits for every child to reach `Destructed`.
1. Transitions to `Destructed`.

As with `construct()`, the order is unspecified and the reference
implementations drive the slots sequentially.

## 4. Selection

The aggregate itself can be selected (via its parent's `Current`), and like any other
`IComponentVM` it exposes `SelectCommand`, `DeselectCommand`, `SelectNextCommand`, and
`SelectPreviousCommand` for navigation within its own parent. The individual `ComponentN`
slots, however, are not selectable — they are the aggregate's fixed structure, not
navigable peers, so there are no `select_component` / `deselect_component` methods.

## 5. Arity rationale

ADR-0007 documents why arities 1–5 were the original supported range, and
ADR-0034 extends the cap to 6. For more than 6 heterogeneous children,
prefer `CompositeVM<VM>` or `GroupVM<VM>` with a heterogeneous-base-type
`VM`, or compose multiple aggregates.

## 6. Conformance

`AGG-001` through `AGG-006` in `12-conformance.md` cover:

- arity-1 component factory invoked on construct
- arity-2 both components reach Constructed
- arity-5 all five components reach Constructed before parent (arity-6
  follows the same pattern)
- ComponentN property change fires on construct
- destruction waits for all children
- arity-6 construction and destruction ordering
