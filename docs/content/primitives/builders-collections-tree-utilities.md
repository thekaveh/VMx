# 6.7. Builders, Collections & Tree Utilities

## When To Use It

Use this area when the question is how to construct primitives, how to expose
observable collections, or how to traverse an existing VM tree.

## Shape And Ownership

Three groups live here:

- immutable fluent builders and additive `create` helpers
- opt-in collection primitives such as `ServicedObservableCollection`,
  `ObservableList`, `ObservableDictionary`, `PagedComposition`, and
  `TokenPagedComposition`
- traversal helpers such as `walk`, `find`, and `walk_expanded`

These pieces are deliberately separate from the core hierarchy so you can opt
into them only where they help.

The core `CompositeVM` / `GroupVM` child surface is a different concern. Both
implement the [VM Collection Contract](vm-collection-contract.md), including
atomic identity-preserving move; selection is a composite-only extension.

## Lifecycle And Messaging

The main operational rules:

- builders are immutable and reusable
- required fields validate on `Build()`
- `ObservableList` and VM container batching are independent scopes
- `ObservableList.replaceAll` / `replace_all` / `ReplaceAll` snapshots input
  before mutation and emits one Reset instead of clear-plus-N-add churn
- `ServicedObservableCollection` publishes local collection events before hub
  messages
- tree utilities are pure reads; they do not trigger lifecycle transitions

Batch handles, paging helpers, disposable collections, and frozen projections
have type-specific terminal behavior cataloged in the
[Disposal Contract](disposal-contract.md). Serviced collections remain
non-owning and never dispose their items.

## Choosing A Collection

| Need                                                                          | Choose                                      |
| ----------------------------------------------------------------------------- | ------------------------------------------- |
| Local granular item streams, a `Count` channel, and nested batch scopes       | `ObservableList<T>`                         |
| Local collection changes plus equivalent messages on an optional external hub | `ServicedObservableCollection<T>`           |
| Child construction/destruction, parent membership, or composite selection     | `GroupVM` / `CompositeVM` child collections |

These contracts are deliberately separate. A serviced collection does not
batch, does not publish `Count`, and does not own item lifecycle. A VM child
collection owns membership and lifecycle; use it when contained values are
children rather than caller-owned data.

## Cross-Language Surface

| Primitive                                                      | Purpose                                        |
| -------------------------------------------------------------- | ---------------------------------------------- |
| Builders                                                       | immutable fluent construction with validation  |
| `ServicedObservableCollection<T>`                              | local changes plus optional hub publication    |
| `ObservableList<T>`                                            | granular events plus atomic whole-list replace |
| `ObservableDictionary<K1, K2, V>`                              | dual-key observable lookup plus live key views |
| `PagedComposition<TVM>` / `TokenPagedComposition<TVM, TToken>` | paging helpers                                 |
| `walk`, `find`, `walk_expanded`                                | tree traversal helpers                         |

## Example

Representative traversal contract:

- `walk(root)` yields root first, then descendants in depth-first pre-order
- `find(root, predicate)` returns the first match in walk order
- `walk_expanded(root)` respects `IExpandable` boundaries

On the collection side, the Notes Workspace note lists and notifications layers
are practical references for observable-list and paging composition.

### Serviced mutation contract

The complete mutation surface is add, remove by value, remove by index,
replace, replace all, move, and clear. See
[Cross-Language Naming](../flavors/cross-language-naming.md) for exact names.

- Value removal targets the first equal match. A missing value returns `false`
  in C#, TypeScript, Swift, and Rust. Python keeps list behavior: successful
  removal returns `None`, while a missing value raises `ValueError`.
- Indexed remove and replace reject invalid bounds before mutation. Python also
  accepts normal negative list indices and reports the resolved nonnegative
  position. Swift's nonthrowing indexed mutators use array preconditions. Rust
  uses `usize`, so negative indices are not representable. Python and Rust
  return the removed or old item from their newly named indexed methods;
  established returns in the other flavors are unchanged.
- `ReplaceAll` first snapshots its input. Iteration failure therefore leaves
  state and streams unchanged. Empty-to-empty is its only no-op; even identical
  non-empty contents produce one Reset.
- `Move` treats both arguments as strict pre-move positions in
  `[0, count)`. Equal positions do nothing; a real move preserves identity and
  emits one Move. Python does not accept negative move indices, and Swift move
  bounds failures throw `VMCollectionIndexError`.
- `Clear` does nothing when already empty and otherwise emits one Reset.

For C#, Python, TypeScript, and Swift, collection messages retain `index` and
add explicit old/new positions:

| Action  | `index`     | old position | new position | Typed items               |
| ------- | ----------- | ------------ | ------------ | ------------------------- |
| Add     | insertion   | `-1`         | insertion    | new                       |
| Remove  | old index   | old index    | `-1`         | old                       |
| Replace | same index  | same index   | same index   | old and new               |
| Move    | destination | source       | destination  | moved item as old and new |
| Reset   | `-1`        | `-1`         | `-1`         | none                      |

The member names follow each language's casing idiom (`OldIndex`,
`old_index`, or `oldIndex`). Rust intentionally keeps its existing non-generic
hub payload: `action`, `old_index: Option<usize>`, and
`new_index: Option<usize>` plus sender/property identity. It has no legacy
`index` field and no item payload.

Every effective mutation changes state first, notifies the local stream second,
and publishes to the optional external hub third. Both observer classes can
read the final state. Delivery is immediate and non-batched. Removing,
replacing, resetting, moving, or clearing never disposes or reparents an item;
the caller keeps lifecycle ownership.

### ObservableList whole-list refresh

Use the flavor-idiomatic `replaceAll` / `replace_all` / `ReplaceAll` when one
semantic refresh supplies a complete snapshot. VMx materializes the input
before changing the backing list, so passing the list or a live view is safe.
Empty-to-empty does nothing; every other call emits exactly one Reset, including
identical non-empty contents. `Count` follows Reset only when cardinality
changes, and both observers see the final snapshot.

Inside an existing list batch, replacement emits nothing immediately and folds
into the outermost Reset. If the batch body fails after replacement, the scope
still closes, publishes that completed mutation once, and rethrows the original
failure. This is list-local batching; it does not suppress VM container events.

### NNx Studio pilot result

A temporary pilot against NNx Studio commit
`d304336799d4f377c9dd34a465072dd697a8fd7b` replaced the run-history refresh's
four-line clear-plus-push loop with `items.replaceAll(runs)`. The package
typecheck and all 322 viewmodel tests passed. A focused 13-to-13 refresh test
observed one Reset instead of the former Reset plus 13 add events: 14
adapter-visible collection notifications became one. The pilot was validation
only and was not pushed to NNx Studio.

## Common Pitfalls

- Mutating a builder and expecting in-place changes. Builder setters return new
  instances.
- Assuming `ObservableList` batch scopes also suppress `CompositeVM` or
  `GroupVM` collection events. They do not.
- Expecting a serviced collection to batch, emit a `Count` channel, or manage
  item lifecycle. Those are intentionally outside its contract.
- Rebuilding a complete list with `clear` plus repeated adds. That produces
  O(n) adapter notifications; use whole-list replacement for one Reset.
- Rewriting custom tree walkers when the built-in helpers already express the
  intended traversal semantics.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [Hierarchical Family](viewmodel-families/hierarchical-family.md)
- [State & Reactive Helpers](state-reactive-helpers.md)
- [VM Collection Contract](vm-collection-contract.md)
