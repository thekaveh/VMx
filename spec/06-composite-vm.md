# 06 — CompositeVM

`CompositeVM<VM>` is a container with selection: it holds an ordered list of child
viewmodels and exposes a `Current` slot that designates at most one child as the
selected one.

## Variants

| Variant                         | Children source                                      | `Current` |
| ------------------------------- | ---------------------------------------------------- | --------- |
| `CompositeVM<VM>` (non-modeled) | builder factory `() -> Iterable<VM>`                 | yes       |
| `CompositeVM<M, VM>` (modeled)  | model factory `() -> Iterable<M>` + mapper `M -> VM` | yes       |

## Members

```
CompositeVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged:
    # IComponentVM members (see 01-concepts.md and 05-component-vm.md):
    Name, Hint, Type=Composite, IsCurrent, IsConstructed, Status,
    SelectCommand, DeselectCommand, SelectNextCommand, SelectPreviousCommand,
    ReconstructCommand, can_construct/construct/..., can_select/select/...

    # CompositeVM-specific:
    Current : VM?                        # may be null; one child or none

    # IList<VM>:
    Add(vm: VM) : void
    Remove(vm: VM) : bool
    Insert(index: int, vm: VM) : void
    RemoveAt(index: int) : void
    Clear() : void
    Count : int
    indexer [i] : VM
    iterator

    # Selection:
    select_component(vm: VM) : void
    deselect_component(vm: VM) : void
    can_select_component(vm: VM) : bool
```

## `Current` contract

- `Current` MAY be `null` (no child selected).
- If `Current` is non-null, it MUST be a member of the children collection.
- Setting `Current` to a value not in the children collection MUST raise.
- Setting `Current = null` is always legal (no-op if already null).
- A change to `Current` fires `PropertyChangedMessage("Current")` and updates the
  affected children's `IsCurrent` (raising their `PropertyChangedMessage("IsCurrent")`).
- If the builder enabled `AsyncSelection(true)`, the setter dispatches the work via
  `IDispatcher.Foreground` and returns immediately. The new `Current` is observable
  only after the dispatcher delivers. If `AsyncSelection(false)` (the default), the
  setter is synchronous.

### `select_component(vm)` / `deselect_component(vm)`

- `select_component(vm)` sets `Current = vm` after verifying `can_select_component(vm)`.
  If the predicate is false, the call raises.
- `deselect_component(vm)` sets `Current = null` after verifying `Current == vm`.
  If `Current != vm`, the call raises.
- `can_select_component(vm)` returns `true` iff `vm ∈ children` and `vm.Status == Constructed`.

## Collection change notification

The collection raises `INotifyCollectionChanged.CollectionChanged` events:

- `Add(vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=Count-1)`.
- `Remove(vm)` → `CollectionChanged(action=Remove, oldItems=[vm], oldIndex=where vm was)`.
- `Insert(i, vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=i)`.
- `RemoveAt(i)` → `CollectionChanged(action=Remove, oldItems=[old], oldIndex=i)`.
- `Clear()` → `CollectionChanged(action=Reset)`.

Implementations MAY suppress notifications during bulk operations; if so, a single
`Reset` event MUST be raised at the end.

## Children construction orchestration

`CompositeVM` overrides the base `construct()` and `destruct()` to coordinate
children:

- `construct()` proceeds through `Destructed → Constructing`. It calls `construct()`
  on every child and listens on the message hub for each child's
  `ConstructionStatusChangedMessage(Constructed)`. Once every child reaches
  `Constructed`, the composite transitions to `Constructed` and emits its own
  status message.
- `destruct()` proceeds through `Constructed → Destructing`. If `Current != null`,
  the composite first sets `Current = null`. It then calls `destruct()` on every
  child and waits for every child's
  `ConstructionStatusChangedMessage(Destructed)`. Once every child reaches
  `Destructed`, the composite transitions to `Destructed`.

The order in which children are visited is unspecified. v1.x reference
implementations drive them sequentially.

A child added via `Add` AFTER the composite has reached `Constructed` does NOT
automatically `construct()` — the host MUST invoke it. (This is a v1.0 limitation;
auto-construct-on-add is a future enhancement.)

## Modeled variant `CompositeVM<M, VM>`

Identical to `CompositeVM<VM>` except the children come from a model factory:

- Builder accepts:
  - `ChildrenModels : () -> Iterable<M>`
  - `ChildModelToChildViewModel : (M) -> VM`
- On `construct()`, the composite first evaluates `ChildrenModels()`, then maps
  each `M` to a `VM`, then orchestrates children construction as above.

The model values themselves are NOT exposed on the composite; the composite is a
container of VMs, not models. Each child VM is responsible for holding its own
model.

## Conformance

`COMP-001` through `COMP-011` in `12-conformance.md` cover:

- collection-change events on add/remove
- `Current` setter behavior (legal/illegal values)
- async selection dispatch (`AsyncSelection(true)` via `IDispatcher.Foreground`)
- `select_component` / `deselect_component` / `can_select_component` predicates
- construction wait-for-all-children
- destruction unsets `Current` before destructing children
- modeled variant maps model factory output to children
- `can_select_component` returns false for non-children
- `Current` setter raises on non-child assignment
- `IsCurrent` change on the previously-Current child dispatches on the foreground scheduler
- `deselect_component` raises when the argument is not `Current`
