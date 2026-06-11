# 05 — ComponentVM

`ComponentVM` is the leaf VM. Use it for any addressable VM that is not itself a
container.

## 1. Variants

| Variant                     | Has `Model` | `Model` mutable | Type identifier     |
| --------------------------- | ----------- | --------------- | ------------------- |
| `ComponentVM` (non-modeled) | no          | n/a             | `Component`         |
| `ComponentVM<M>` (modeled)  | yes         | yes             | `Component`         |
| `ReadonlyComponentVM<M>`    | yes         | no              | `ReadOnlyComponent` |

All three variants share the `IComponentVM` baseline (see `01-concepts.md`).

## 2. Members (every variant)

```
ComponentVM:
    Name : string                          # immutable post-construction
    Hint : string                          # immutable post-construction
    Type : ViewModelType                   # immutable, equals "Component" or "ReadOnlyComponent"
    IsCurrent : bool                       # parent-derived; raised through PropertyChanged
    IsConstructed : bool                   # equals Status == Constructed
    Status : ConstructionStatus            # see 02-lifecycle.md

    # Built-in commands
    SelectCommand : ICommand
    DeselectCommand : ICommand
    SelectNextCommand : ICommand
    SelectPreviousCommand : ICommand
    ReconstructCommand : ICommand

    # Lifecycle operations
    can_construct() : bool
    construct() : void  /  async
    can_destruct() : bool
    destruct() : void  /  async
    can_reconstruct() : bool
    reconstruct() : void  /  async
    dispose() : void

    # Selection operations
    can_select() : bool
    select() : void
    can_deselect() : bool
    deselect() : void
```

## 3. Modeled variant additions (`ComponentVM<M>`)

```
ComponentVM<M> : ComponentVM:
    Model : M                              # settable; setting fires PropertyChangedMessage("Model")
    ModeledHint : string                   # derived; recomputed when Model changes
```

The setter for `Model`:

1. If the new value equals the old (`==` semantics per language), no message is
   emitted and no derived properties update.
1. Otherwise, the field is replaced, `PropertyChangedMessage("Model")` is emitted,
   and if `ModeledHint` is wired (see below), it is recomputed and
   `PropertyChangedMessage("ModeledHint")` is emitted.

### 3.1 `ModeledHint`

`ModeledHint` is a derived string computed from `Model` via a `model_hinter`
function provided at build time:

```
ModeledHinter : (M) -> string
```

If no `ModeledHinter` is configured, `ModeledHint` returns the empty string.

### 3.2 `OnModelChanged`

The builder accepts an `OnModelChanged` callback (`(M) -> void`). When the model
setter accepts a new value, this callback is invoked AFTER the
`PropertyChangedMessage` is emitted. Use it to wire model-driven side effects.

## 4. Readonly variant (`ReadonlyComponentVM<M>`)

Same surface as `ComponentVM<M>` minus the `Model` setter. The model is provided at
build time and is final. `ModeledHint` remains derived but stable (the model never
changes).

`Type` equals `ReadOnlyComponent`.

## 5. Built-in commands

| Command                 | Predicate                     | Task                                        |
| ----------------------- | ----------------------------- | ------------------------------------------- |
| `SelectCommand`         | `can_select()`                | `select()`                                  |
| `DeselectCommand`       | `can_deselect()`              | `deselect()`                                |
| `SelectNextCommand`     | parent has a "next" child     | move parent's `Current` to next sibling     |
| `SelectPreviousCommand` | parent has a "previous" child | move parent's `Current` to previous sibling |
| `ReconstructCommand`    | `can_reconstruct()`           | `reconstruct()`                             |

All five commands re-evaluate their predicates on every relevant `Status` change of
the VM (via a trigger derived from `Status`).

## 6. Selection predicates

```
can_select() returns true iff:
  - Parent is not null
  - Parent.Current != this
  - Status == Constructed

can_deselect() returns true iff:
  - Parent is not null
  - Parent.Current == this
```

`select()` calls `parent.select_component(this)`. `deselect()` calls
`parent.deselect_component(this)`. The selection contract is defined in
`06-composite-vm.md`.

## 7. Construction

Construction in this variant amounts to publishing the status transitions. There is
no child orchestration (components have no children). Override hooks for user code
exist (`OnConstruct` / `OnDestruct` callbacks at build time) — see `10-builders.md`.

## 8. `IExpandable` integration (spec v2.0)

A consumer that wants a VM with expand/collapse semantics implements the
`IExpandable` capability (see `14-capabilities.md` and ADR-0015) and
supplies an `is_expanded` accessor. The base `ComponentVM` does NOT
implement `IExpandable`; this preserves the opt-in rule from chapter 14.

A convenience helper per flavor (`ExpandableState`) bundles the state +
toggle + change notification for VMs that want to opt in:

```
ExpandableState : IExpandable, ICollapsible, IExpansionTogglable:
    IsExpanded : bool                       # current state (read-only; mutate via Expand/Collapse/Toggle)
    Expand() / Collapse() / ToggleExpansion()
    IsExpandedChanged : Observable<bool>    # emits on every change
```

The helper is composition-friendly: VMs that want expand/collapse hold an
`ExpandableState` and delegate the capability members to it. The
`walk_expanded` tree utility (see `13-tree-utilities.md`) recognizes any
`IExpandable` implementation and gates descent on `IsExpanded`.

## 9. Conformance

`CVM-001` through `CVM-006` and `EXP-001` through `EXP-005` in
`12-conformance.md` cover:

- status emission on construct
- modeled `Model` setter PropertyChanged behavior
- readonly variant has no `Model` setter
- `ModeledHint` recomputation
- `Name`/`Hint`/`Type` immutability
- `SelectCommand` predicate behavior
