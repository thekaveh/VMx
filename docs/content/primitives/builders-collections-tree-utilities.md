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

## Lifecycle And Messaging

The main operational rules:

- builders are immutable and reusable
- required fields validate on `Build()`
- `ObservableList` and VM container batching are independent scopes
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
| `ObservableList<T>`                                            | granular per-mutation list events              |
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

## Common Pitfalls

- Mutating a builder and expecting in-place changes. Builder setters return new
  instances.
- Assuming `ObservableList` batch scopes also suppress `CompositeVM` or
  `GroupVM` collection events. They do not.
- Rewriting custom tree walkers when the built-in helpers already express the
  intended traversal semantics.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [Hierarchical Family](viewmodel-families/hierarchical-family.md)
- [State & Reactive Helpers](state-reactive-helpers.md)
