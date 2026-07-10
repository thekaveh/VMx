# 06 — CompositeVM

`CompositeVM<VM>` is a container with selection: it holds an ordered list of child
viewmodels and exposes a `Current` slot that designates at most one child as the
selected one.

## 1. Variants

| Variant                         | Children source                                      | `Current` |
| ------------------------------- | ---------------------------------------------------- | --------- |
| `CompositeVM<VM>` (non-modeled) | builder factory `() -> Iterable<VM>`                 | yes       |
| `CompositeVM<M, VM>` (modeled)  | model factory `() -> Iterable<M>` + mapper `M -> VM` | yes       |

For domains that are natively recursive (trees), use `HierarchicalVM<TModel, TVM>` (chapter 18) instead of
recursively nesting `CompositeVM<M, VM>`. `HierarchicalVM` provides built-in parent / depth / path semantics
plus depth-first construction order.

## 2. Members

```
CompositeVM<VM> : ISelectableVmCollection<VM>:
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
    Replace(index: int, vm: VM) : void
    Clear() : void
    Move(fromIndex: int, toIndex: int) : void
    Count : int
    indexer [i] : VM
    iterator

    # Selection:
    select_component(vm: VM) : void
    deselect_component(vm: VM) : void
    can_select_component(vm: VM) : bool
```

### 2.1 The `ICompositeVM<VM>` contract

`ICompositeVM<VM>` is the compatibility name every `CompositeVM<VM>` realizes.
It extends the shared selectable VM collection capability (chapter 01 §1.4,
ADR-0085), which combines the non-selecting collection surface with
the members above describe:

```
ICompositeVM<VM> : ISelectableVmCollection<VM>:
    Current : VM?                         # selection slot (§3)
    select_component(vm: VM) : void       # guarded selection (§3.1)
    deselect_component(vm: VM) : void
    can_select_component(vm: VM) : bool
```

The shared collection surface contributes `Add` / `Remove` / `Insert` /
`RemoveAt` / replacement / `Clear` / `Move` / `BatchUpdate` / `Count` / the
indexer / iteration / collection-change observation; `Current` and the three
`*_component` methods are the composite-specific additions over the base
`IComponentVM`. This is the interface `ForwardingCompositeVM<VM>`
(`09-forwarding.md`) wraps and delegates; chapter 09 references this declaration
as canonical rather than re-declaring it inline. `ICompositeVM<VM>` is the
language-neutral contract name; each flavor realizes it per the ADR-0006 idiom:
C# ships the literal `ICompositeVM<VM>` interface, Python the structural
`CompositeVMProto` (the `…Proto` convention catalogued in ADR-0009), and
TypeScript the structural `CompositeVMBase<VM>` shape the forwarding decorator
wraps.

## 3. `Current` contract

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

### 3.1 `select_component(vm)` / `deselect_component(vm)`

- `select_component(vm)` sets `Current = vm` after verifying `can_select_component(vm)`.
  If the predicate is false, the call raises.
- `deselect_component(vm)` sets `Current = null` after verifying `Current == vm`.
  If `Current != vm`, the call raises. This is a guarded convenience; the raw
  `Current = null` setter (§3) stays unconditional.
- `can_select_component(vm)` returns `true` iff `vm ∈ children` and `vm.Status == Constructed`.

### 3.2 Initial `Current` selection and change callback (spec v2.6.0)

`CompositeVMBuilder<VM>` and `CompositeVMOfMBuilder<M, VM>` accept two optional declarative hooks for `Current`:

- `Current(selector)` — `selector: Iterable<VM> -> VM | None`. Invoked once during the composite's construct phase, **after** all children have transitioned to `Constructed` and **before** the composite reaches `Constructed`. The composite assigns `Current` to the selector's return value through an internal **non-raising validated assignment** — NOT the guarded `select_component` path, which raises on a non-child (§3.1, `COMP-009`). If the selector returns a contained child, the normal `Current` transition fires (`PropertyChangedMessage("Current")` plus the `IsCurrent` updates of §3). If the selector returns `null` or a value not contained in the composite, the assignment is a **silent no-op**: `Current` stays at its prior value (initially `null`) and no notification fires. (ADR-0042 §5.1 phrased this as "the `SelectComponent` path"; ADR-0050 corrects the wording to the non-raising assignment that the reference implementations and `COMP-025` actually exercise, reconciling it with §5.4's no-op rule.)
- `OnCurrentChanged(callback)` — `callback: (VM | None) -> void`. Invoked synchronously after every `Current` transition, **after** the state is updated and the hub publishes `PropertyChangedMessage("Current")`. Receives the new `Current` value (which may be `null`).

Both hooks are optional; absent calls yield v2.5.0 behavior. The hooks compose: if both are present, the initial selector's assignment triggers the callback exactly once.

Conformance: `COMP-025` (initial-current selector), `COMP-026` (`OnCurrentChanged` callback fires on `Current` change).

## 4. Collection change notification

The collection raises `INotifyCollectionChanged.CollectionChanged` events:

- `Add(vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=Count-1)`.
- `Remove(vm)` → `CollectionChanged(action=Remove, oldItems=[vm], oldIndex=where vm was)`.
- `Insert(i, vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=i)`.
- `RemoveAt(i)` → `CollectionChanged(action=Remove, oldItems=[old], oldIndex=i)`.
- `Move(from, to)` → one `CollectionChanged(action=Move, oldItems=[vm], newItems=[vm], oldIndex=from, newIndex=to)`.
- `Clear()` → `CollectionChanged(action=Reset)`.

Move follows chapter 01 §1.4 exactly: indices are validated before mutation,
same-index moves emit nothing, and a successful move preserves child identity,
parent, lifecycle, subscriptions, and `Current`.

### 4.1 Batch updates (spec v1.1)

A composite MUST expose a `BatchUpdate()` method returning an `IDisposable` /
context manager. While at least one batch handle is live, mutations (`Add`,
`Insert`, `Remove`, `RemoveAt`, `Clear`, indexer set) MUST NOT raise individual
`CollectionChanged` events. Move participates as one mutation. When the last
live handle is disposed:

- If any mutations occurred during the batch, a single
  `CollectionChanged(action=Reset)` MUST be raised.
- If no mutations occurred, no event is raised.

Nested batches are ref-counted: only the outermost completion fires the `Reset`.

## 5. Children construction orchestration

The non-modeled `CompositeVM<VM>` may be built with the fluent builder or the
additive positional-options form (`Create`/`create` — see `10-builders.md §7`);
both validate the same required fields (`name`, services, `children`) and produce
an identical VM.

`CompositeVM` overrides the base `construct()` and `destruct()` to coordinate
children:

- `construct()` proceeds through `Destructed → Constructing`. It calls `construct()`
  on every child; each call returns once that child has reached `Constructed`
  (per the synchronous lifecycle contract — ADR-0008). Once every child is
  `Constructed`, the composite transitions to `Constructed` and emits its own
  status message. An asynchronous flavor MAY instead observe the children's
  `ConstructionStatusChangedMessage(Constructed)` on the hub; the synchronous
  default is a strict subset of that behavior.
- `destruct()` proceeds through `Constructed → Destructing`. If `Current != null`,
  the composite first sets `Current = null`. It then calls `destruct()` on every
  child; each call returns once that child reaches `Destructed`. Once every
  child is `Destructed`, the composite transitions to `Destructed`.

The order in which children are visited is unspecified. The reference
implementations in the full-parity flavors
drive them sequentially.

### 5.1 Add after Constructed

A child added via `Add` AFTER the composite has reached `Constructed` does NOT
automatically `construct()` by default — the host MUST invoke it.

A composite built with `AutoConstructOnAdd(true)` (added in spec v1.1) MUST
automatically call `construct()` on any child added via `Add` / `Insert` after
the composite reaches `Constructed`, completing the child's transition to
`Constructed` BEFORE the `CollectionChanged` event fires. Builds default to
`false` for backwards compatibility.

## 6. Modeled variant `CompositeVM<M, VM>`

Identical to `CompositeVM<VM>` except the children come from a model factory:

- Builder accepts:
  - `ChildrenModels : () -> Iterable<M>`
  - `ChildModelToChildViewModel : (M) -> VM`
- On `construct()`, the composite first evaluates `ChildrenModels()`, then maps
  each `M` to a `VM`, then orchestrates children construction as above.

The model values themselves are NOT exposed on the composite; the composite is a
container of VMs, not models. Each child VM is responsible for holding its own
model.

## 7. Modeled CRUD commands (spec v2.0)

A modeled composite (`CompositeVM<M, VM>`) MAY opt into a CRUD command set via
the `ModeledCrudCommands<M, VM>` helper (designed in ADR-0016):

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
- An optional `current_changed` trigger (`Observable<Unit>`) — typically the
  owning composite's current-child-changed stream — that re-evaluates the
  Update/Delete `CanExecute` when the selection changes (spec v3, ADR-0049).

Behavior:

- `CreateNewCommand.CanExecute` returns `true` whenever the helper exists.
- `UpdateCurrentCommand.CanExecute` returns `true` iff `current != null`.
- `DeleteCurrentCommand.CanExecute` returns `true` iff `current != null`.
- When a confirm delegate is supplied, the command is wrapped in a
  `ConfirmationDecoratorCommand` and `Execute` resolves the confirm gate
  before invoking the action.
- The `CanExecute` predicate **values** above (`true` iff `current != null`) are
  verified by `COMP-021` / `COMP-023`. Their **reactivity** is separate: because
  the predicates read the mutable `current` provider, `CanExecuteChanged` cannot
  fire on its own (chapter 04 §4), so a bound button's enabled state would go
  stale on every selection change. When a `current_changed` trigger is supplied,
  the helper wires it as a `Triggers` source on the Update and Delete commands so
  each `CanExecute` is re-evaluated and `CanExecuteChanged` fires the moment the
  selection changes (chapter 04 §4.2, ADR-0049). Supplying the trigger is
  RECOMMENDED whenever the commands are bound to UI; omitting it leaves
  `CanExecute` correct on demand but non-reactive. Exposing the optional
  `current_changed` parameter is, per ADR-0049, a clarification first realized in
  C# (VMX-011) and also exposed by Swift's `ModeledCrudCommands`; Python and
  TypeScript compose the same reactivity through the base `Triggers` mechanism
  (chapter 04 §4.2).

The helper is opt-in; the base `CompositeVM<M, VM>` retains its current shape.

## 8. Search / filter (spec v2.0)

A composite (or group) MAY opt into search/filter via the `SearchableState`
helper, which implements `ISearchable` from chapter 14 (designed in ADR-0014):

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

## 9. Filtered composite views (spec v3.1)

`FilteredCompositeVM<VM>` provides a cursor-owning visible projection over a
source `CompositeVM<VM>`.

```
FilteredCompositeVM<VM>:
    source       : CompositeVM<VM>
    predicate    : (VM) -> bool
    Visible      : IReadOnlyList<VM>
    VisibleCount : int
    Current      : VM?
    Changed      : Observable/Event

    SetPredicate(predicate)
    SetCurrent(vm?)
    MoveToNextVisible()
    MoveToPreviousVisible()
    Dispose()
```

The source composite remains the owner of child membership and lifecycle. The
filtered view owns the visible projection and its own current slot in the visible
domain. When the source mutates or the predicate changes, the projection is
recomputed and current is reconciled according to a cursor policy:

- `SnapToFirst`: if current is filtered out, select the first visible item.
- `Clear`: if current is filtered out, clear current.
- `PreserveIfVisible`: keep current only if it remains visible, otherwise clear.

`ScoredFilteredCompositeVM<VM>` filters out null/absent scores and orders visible
items by descending score with source-order stable tie breaks. `RefreshScores()`
forces a recompute when external score state changes.

## 10. Conformance

`COMP-001` through `COMP-013`, `COMP-014` through `COMP-018`, (the
modeled-CRUD additions documented later) `COMP-019` through `COMP-024`, and
the builder hooks `COMP-025` and `COMP-026` (see below), plus filtered/scored
view IDs `COMP-028` through `COMP-037`, in
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
- filtered visible projections and visible-domain current
- scored filtering with stable score ordering

The builder hooks introduced in §3.2 are covered by:

- `COMP-025` — `Current(selector)` builder hook drives initial selection during construct.
- `COMP-026` — `OnCurrentChanged(callback)` fires synchronously after each `Current` change.

The `Parent` back-reference wiring (declared in `01-concepts.md` §1.3 and
`05-component-vm.md` §6.1) is covered by:

- `COMP-027` — `Add` sets a child's `Parent` (the child becomes selectable and
  `select()` delegates through it); `Remove` clears it (the child is no longer
  selectable and `select()` becomes a no-op).

Cross-cutting `DISP-001` covers repeated parent cascades, and `DISP-006`
covers idempotent batch/projection disposal without changing this chapter's
ownership rules.
