# 07 — GroupVM

`GroupVM<VM>` is a container of peers — children with no selection. It is identical
to `CompositeVM<VM>` minus the `Current` slot and minus the selection-related
members and commands.

## 1. Members

```
GroupVM<VM> : IVmCollection<VM>:
    # IComponentVM members:
    Name, Hint, Type=Group, IsCurrent, IsConstructed, Status,
    SelectCommand, DeselectCommand, SelectNextCommand, SelectPreviousCommand,
    ReconstructCommand, can_construct/construct/..., can_select/select/...

    # IList<VM>:
    Add, Remove, Insert, RemoveAt, Replace, Clear, Move, BatchUpdate,
    Count, indexer, iterator, CollectionChanged
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
Children added to a `GroupVM` are peers: their inherited `can_select` /
`CanSelect` / `canSelect` predicate MUST return `false` while the parent is the
group, and their inherited select command MUST be disabled. Calling `select()` /
`Select()` on such a child is a no-op.

The shared non-selecting collection capability is defined in chapter 01 §1.4
and ADR-0085. Group implements that complete capability but does not implement
the selectable extension. `Move(from, to)` validates both pre-move indices,
emits one `Move` event with the same child and both indices, and preserves
identity, parent, lifecycle, subscriptions, and auto-construction state.

### 1.1 Atomic child ownership transfer (spec v3.21)

Group membership follows chapter 06 §4.2 exactly. Adding or inserting a child
owned by another mutable composite or group removes it from the old membership
before adding it here, without destructing or disposing it. Duplicate identity
and self/ancestor cycles fail before mutation. Replacement and lazy population
are transactional under the destination/old-parent isolation rules in chapter
06 §4.2. Failure restores the old parent, index, selection state (if the old
parent is a composite), parent link, population retryability, and membership
event stream. Lifecycle compensation failure is surfaced rather than swallowed,
as qualified by ADR-0118. Disposal requested while an old-parent transfer is
staged follows chapter 06 §4.2 and ADR-0122: commit or rollback reaches a stable
membership boundary before the old parent snapshots and cascades its children.

## 2. Children construction orchestration

Identical to `CompositeVM`: `construct()` waits for every child to reach
`Constructed`; `destruct()` waits for every child to reach `Destructed`. The
order in which children are visited is unspecified.

## 3. Builder

The builder accepts:

- `children : () -> Iterable<VM>` (factory, evaluated on `construct()`).

The modeled variant (if needed) follows the same pattern as `CompositeVM<M, VM>`.
Only the non-modeled variant currently ships.

`GroupVM<VM>` may also be built with the additive positional-options form
(`Create`/`create` — see `10-builders.md §7`), which validates the same required
fields (`name`, services, `children`) and produces an identical VM.

## 4. Auto-construct on add (spec v1.1)

A group built with `AutoConstructOnAdd(true)` MUST automatically call
`construct()` on any child added via `Add` / `Insert` after the group reaches
`Constructed`, completing the child's transition BEFORE the `CollectionChanged`
event fires. The default is `false`.

## 5. Batch updates (spec v1.1)

A group MUST expose a `BatchUpdate()` method returning an `IDisposable` /
context manager. While at least one batch handle is live, mutations MUST NOT
raise individual `CollectionChanged` events. When the last live handle is
disposed, if any mutations occurred a single
`CollectionChanged(action=Reset)` MUST be raised. Nested batches are
ref-counted.

A same-index move is not a mutation and does not dirty the batch. A non-no-op
move inside a batch contributes to the one outer `Reset`.

## 6. Search / filter (spec v2.0)

A group MAY opt into search/filter via the same `SearchableState` helper
documented in `06-composite-vm.md` §"Search / filter". Behavior is identical
in the group context; only the conformance IDs differ (`GRP-007..GRP-010`).

## 7. Conformance

`GRP-001` through `GRP-006`, `GRP-007` through `GRP-010`, and `GRP-011`
in `12-conformance.md` cover:

- collection-change events on add/remove
- absence of `Current`
- construction waits for all children
- destruction waits for all children
- (v1.1) `AutoConstructOnAdd(true)` auto-constructs children added after the group is `Constructed`
- (v1.1) `BatchUpdate()` suppresses per-mutation events and emits a single `Reset` at completion
- group children are peers whose inherited select command is disabled
- atomic cross-parent transfer, duplicate/cycle rejection, isolated rollback
  with explicit compensation failure, and old-removal-before-new-add
  observation order (`COMP-038` through `COMP-041`)

`DISP-001` and `DISP-006` provide the cross-cutting repeated-cascade and
batch-handle idempotency assertions (ADR-0084).
