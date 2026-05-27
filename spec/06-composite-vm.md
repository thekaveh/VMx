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

### Batch updates (spec v1.1)

A composite MUST expose a `BatchUpdate()` method returning an `IDisposable` /
context manager. While at least one batch handle is live, mutations (`Add`,
`Insert`, `Remove`, `RemoveAt`, `Clear`, indexer set) MUST NOT raise individual
`CollectionChanged` events. When the last live handle is disposed:

- If any mutations occurred during the batch, a single
  `CollectionChanged(action=Reset)` MUST be raised.
- If no mutations occurred, no event is raised.

Nested batches are ref-counted: only the outermost completion fires the `Reset`.

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

### Add after Constructed

A child added via `Add` AFTER the composite has reached `Constructed` does NOT
automatically `construct()` by default — the host MUST invoke it.

A composite built with `AutoConstructOnAdd(true)` (added in spec v1.1) MUST
automatically call `construct()` on any child added via `Add` / `Insert` after
the composite reaches `Constructed`, completing the child's transition to
`Constructed` BEFORE the `CollectionChanged` event fires. Builds default to
`false` for backwards compatibility.

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

## Modeled CRUD commands (spec v2.0)

A modeled composite (`CompositeVM<M, VM>`) MAY opt into a CRUD command set via
the `ModeledCrudCommands<M, VM>` helper:

```
ModeledCrudCommands<M, VM>:
    CreateNewCommand    : ICommand    # invokes the create-new action
    UpdateCurrentCommand: ICommand    # invokes update(current_vm) when current != null
    DeleteCurrentCommand: ICommand    # invokes delete(current_vm) when current != null
```

The helper takes:

- A `current` provider (a function returning the current VM or `null`).
- A `create_new` action (a parameterless callable).
- An `update_current` action (a callable taking the current VM).
- A `delete_current` action (a callable taking the current VM).
- Optional `confirm_update` / `confirm_delete` async delegates that gate
  execution via `ConfirmationDecoratorCommand` (see chapter 04 §Decorators).

Behavior:

- `CreateNewCommand.CanExecute` returns `true` whenever the helper exists.
- `UpdateCurrentCommand.CanExecute` returns `true` iff `current != null`.
- `DeleteCurrentCommand.CanExecute` returns `true` iff `current != null`.
- When a confirm delegate is supplied, the command is wrapped in a
  `ConfirmationDecoratorCommand` and `Execute` resolves the confirm gate
  before invoking the action.

The helper is opt-in; the base `CompositeVM<M, VM>` retains its current shape.

## Search / filter (spec v2.0)

A composite (or group) MAY opt into search/filter via the `SearchableState`
helper, which implements `ISearchable` from chapter 14:

```
SearchableState<TItem>:
    SearchTerm : string                          # read/write
    SearchTermChanged : Observable<string>        # debounced (default 1s, configurable)
    Predicate : (TItem, string) -> bool           # user-supplied
    Items : Iterable<TItem>                       # current source set
    Filtered : Observable<list<TItem>>            # filtered set, recomputed on
                                                 # debounced SearchTerm change or Items change
    can_search() : bool
    search() : void                              # force immediate recompute
```

Behavior:

- Setting `SearchTerm` to a new value triggers a debounced emission on
  `SearchTermChanged`. The default debounce is **1 second**; consumers may
  override via builder/constructor.
- After the debounce, the helper recomputes `Filtered` by applying
  `Predicate(item, search_term)` to each item in `Items` and emitting the
  list of matches.
- `Predicate` is user-supplied; common defaults (case-insensitive substring
  match) are NOT mandated by the spec.
- `search()` forces an immediate recompute, bypassing the debounce.
- `can_search()` returns `true` when at least one item is present (helpers
  MAY relax this).

Consumers wire `SearchableState` to a composite by passing
`composite as Iterable<TItem>` as `Items`. The helper is opt-in; the base
`CompositeVM<VM>` retains its current shape unchanged.

## Conformance

`COMP-001` through `COMP-013`, `COMP-014` through `COMP-018`, and (the
modeled-CRUD additions documented later) `COMP-019` through `COMP-024`, in
`12-conformance.md` cover:

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
- (v1.1) `AutoConstructOnAdd(true)` auto-constructs children added after the composite is `Constructed`
- (v1.1) `BatchUpdate()` suppresses per-mutation events and emits a single `Reset` at completion
