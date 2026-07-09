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
    PropertyChanged : per-instance stream  # flavor-idiomatic; see §2.1

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

Every variant also holds an internal `Parent` back-reference (see `01-concepts.md`
§1.3 and §6.1 below). It is not a public, consumer-settable member and does not emit
a `PropertyChangedMessage`; it is listed here only because the selection predicates
in §6 read it.

### 2.1 Per-instance property change surface

Every component exposes a property-change surface scoped to that VM instance, so
views do not need to subscribe to a shared hub and filter by sender when they only
care about one VM:

| Flavor     | Surface                  | Payload                      |
| ---------- | ------------------------ | ---------------------------- |
| C#         | `INotifyPropertyChanged` | `PropertyChangedEventArgs`   |
| Python     | `property_changed`       | changed property name string |
| TypeScript | `propertyChanged`        | changed property name string |
| Swift      | `propertyChanged`        | changed property name string |

The shared hub `PropertyChangedMessage` path remains the cross-VM coordination
channel. The per-instance surface is the preferred binding target for a single
VM's view adapter.

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

`SelectNextCommand` / `SelectPreviousCommand` are present on the `IComponentVM`
baseline for a uniform surface, but a leaf VM does not enumerate its parent's
children. In the reference implementations of the full-parity flavors their predicate
therefore **always returns `false`** and their task is a **no-op** (sibling
navigation, when a host wants it, is driven by the container, not by the leaf). This
inert behaviour is the normative contract for the base commands and is asserted for
the group case by `GRP-002`; the table rows above describe the *intended* sibling
semantics a container MAY implement, not behaviour the base leaf performs.

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

`Parent.Current` denotes the container's `Current` slot, which only a `CompositeVM`
owns. A `GroupVM` has no selection slot; its `Current` is conceptually always empty,
so `Parent.Current != this` holds for every group child. (All full-parity flavors add a
"parent supports child selection" guard — `Parent.SupportsChildSelection` /
`supports_child_selection`, which a `GroupVM` reports as `false` and a `CompositeVM`
as `true` — so a group child's `can_select` / `can_deselect` is `false` in every
flavor. That uniform guard is precisely why chapter 07 §1's requirement — a group
child's inherited `can_select` MUST return `false` while the parent is the group —
holds everywhere. The guard is unaffected by the `Parent` declaration here.)

### 6.1 The `Parent` back-reference

The selection predicates above and `IsCurrent` read an internal `Parent`
back-reference declared on the `IComponentVM` baseline (`01-concepts.md` §1.3):

- `Parent` is `null` for a VM that is not a member of any container.
- A container (`CompositeVM` / `GroupVM`) **sets** the child's `Parent` to itself
  when the child is added (`Add` / `Insert`, or wired as a child at build time) and
  **clears** it to `null` when the child is removed (`Remove` / `RemoveAt` /
  `Clear`) or re-parented into another container.
- `Parent` is not consumer-settable and is not observable: changing it does NOT emit
  a `PropertyChangedMessage`. Its effect is observed indirectly through the selection
  predicates (a freshly built, un-parented VM has `can_select() == false`; after it
  is added to a `CompositeVM` and constructed, `can_select()` becomes `true`; after
  removal it is `false` again) and through `select()` / `deselect()` delegating to
  the parent (a no-op once `Parent` is `null`).

The set-on-add / clear-on-remove wiring is conformance-tested by `COMP-027`.

## 7. Construction

Construction in this variant amounts to publishing the status transitions. There is
no child orchestration (components have no children). Override hooks for user code
exist (`OnConstruct` / `OnDestruct` callbacks at build time) — see `10-builders.md`.
`ComponentVM` and `ComponentVM<M>` may be built either with the fluent builder or
the additive positional-options form (`Create`/`create` — see `10-builders.md §7`);
both validate the same required fields and produce an identical VM.

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
