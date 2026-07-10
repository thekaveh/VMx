# 6.9. VM Collection Contract

## When To Use It

Depend on the VM collection capability when a consumer needs ordered child
viewmodels but should work with either a selectable `CompositeVM` or a peer-only
`GroupVM`. Typical consumers are UI list adapters, drag-reorder handlers,
collection bridges, and instrumentation.

Use the selectable extension only when the consumer genuinely reads or changes
`Current`. A group deliberately has no placeholder current slot.

## Capability Shape

The base capability provides:

- count, indexed lookup, and ordered iteration
- collection-change observation
- add, insert, remove, indexed remove, replace, and clear
- `move(from, to)` for an existing child
- a ref-counted batch scope

Selection is layered on top with `Current`, select, deselect, and the selection
predicate.

| Flavor     | Base capability         | Selectable extension              | Move spelling                     |
| ---------- | ----------------------- | --------------------------------- | --------------------------------- |
| C#         | `IVmCollection<VM>`     | `ISelectableVmCollection<VM>`     | `Move(fromIndex, toIndex)`        |
| Python     | `VmCollectionProto[VM]` | `SelectableVmCollectionProto[VM]` | `move(from_index, to_index)`      |
| TypeScript | `IVmCollection<VM>`     | `ISelectableVmCollection<VM>`     | `move(fromIndex, toIndex)`        |
| Swift      | `VMCollection`          | `SelectableVMCollection`          | `move(from:to:)`                  |
| Rust       | `VmCollection<T>`       | `SelectableVmCollection<T>`       | `move_item(from_index, to_index)` |

`CompositeVM` implements the selectable extension. `GroupVM` implements only
the base capability.

## Move Semantics

Move is an ordering change, not remove plus add:

1. `from` and `to` both address the collection before the move and must be in
   `[0, Count)`.
1. The child occupies `to` afterward; intervening children shift.
1. Equal indices do nothing and emit nothing.
1. Invalid indices raise a catchable flavor-idiomatic bounds error before any
   state or event changes.
1. A successful move emits one `Move` event with the same child in the old and
   new item fields and with both indices.

Inside a batch, a non-no-op move is suppressed with the other granular events
and produces one `Reset` when the outermost batch closes. A same-index move
does not dirty the batch.

## Identity And Lifecycle Guarantees

Move never reconstructs the child or creates a replacement object. It preserves:

- object identity and consumer subscriptions
- parent wiring
- lifecycle status
- `IsCurrent`
- a composite's `Current` reference
- the auto-construction count

This distinction matters in UI hosts. A reorder keeps component keys, local UI
state, focus, and subscriptions attached to the same VM. Rebuilding a list does
not offer that guarantee.

## TypeScript React Adapter

The Notes Showcase `useVmCollection` bridge accepts `IVmCollection<VM>` and can
therefore render either family without casts:

```ts
function useVmCollection<VM extends ComponentVMBase>(
  collection: IVmCollection<VM>,
): VM[];
```

Subscribe to `collectionChanged`, then take a fresh `Array.from(collection)`
snapshot. A `Move` notification causes one render with the final order.

## Common Pitfalls

- Adding `Current` to a generic collection adapter. That needlessly excludes
  groups and reintroduces the cast this capability removes.
- Implementing reorder as remove/add. Observers see a transient absence and may
  clear selection or run parent/lifecycle logic.
- Accepting an insertion endpoint (`to == Count`). Move targets existing final
  positions, so both indices are strictly less than `Count`.
- Treating a same-index move as a batch mutation. It is a true no-op.

## Conformance And Decisions

ADR-0085 records the design. `COL-032..039` prove the capability split, both
directions, no-op and invalid bounds, invariant preservation, batch behavior,
and auto-construction interaction in all five flavors.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [Group Family](viewmodel-families/group-family.md)
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
- [Specification & Conformance](../specification-conformance.md)
