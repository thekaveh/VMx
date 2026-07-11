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

## Cross-Language Surface

| Primitive                                                      | Purpose                                        |
| -------------------------------------------------------------- | ---------------------------------------------- |
| Builders                                                       | immutable fluent construction with validation  |
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
are the practical references for observable-list and paging composition.

### Whole-list refresh

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
- Rebuilding a complete list with `clear` plus repeated adds. That produces
  O(n) adapter notifications; use whole-list replacement for one Reset.
- Rewriting custom tree walkers when the built-in helpers already express the
  intended traversal semantics.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [Hierarchical Family](viewmodel-families/hierarchical-family.md)
- [State & Reactive Helpers](state-reactive-helpers.md)
- [VM Collection Contract](vm-collection-contract.md)
