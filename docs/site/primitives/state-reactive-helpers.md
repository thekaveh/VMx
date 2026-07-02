# State & Reactive Helpers

## When To Use It

Use these helpers when the VM shape is already correct, but you need reusable
reactive behavior layered onto it: search, expand/collapse state, derived
values, active-key coordination, or edit/revert state.

## Shape And Ownership

The main helpers in this area are:

- `SearchableState<TItem>` for debounced filtering/search
- `ExpandableState` for expand/collapse capability composition
- `DerivedProperty<TValue>` for N-source computed values
- `DiscriminatorVM<TKey>` for one active key with modal precedence
- `FormVM<TM>` for snapshot/revert/approve flows

These primitives own subscriptions and derived state, but they are usually
composed inside a larger VM rather than used as the outer VM boundary.

## Lifecycle And Messaging

The lifecycle rule is simple: if a helper owns subscriptions, dispose it with
its owner. That matters especially for `DerivedProperty`, `SearchableState`, and
`DiscriminatorVM`.

`DerivedProperty` is also the standard replacement for older ad hoc
initialization-token patterns: subscribe once, multicast value changes, and tear
down cleanly on disposal.

## Cross-Language Surface

| Helper                    | Key surface                                      |
| ------------------------- | ------------------------------------------------ |
| `SearchableState<TItem>`  | search term, filtered view, force-search         |
| `ExpandableState`         | expanded flag, expand/collapse/toggle            |
| `DerivedProperty<TValue>` | value, value-changed, optional write-back        |
| `DiscriminatorVM<TKey>`   | active key, modal stack helpers                  |
| `FormVM<TM>`              | model, snapshot, dirty/valid state, approve/deny |

## Example

The Notes Workspace examples combine several helpers inside one editor and one
status surface:

- `NoteFormVM` composes `FormVM`, `DiscriminatorVM`, and `SearchableState`
- status and action bars compose `DerivedProperty`
- tree-like consumers can compose `ExpandableState` with hierarchical nodes

That composition style is the norm in VMx.

## Common Pitfalls

- Re-implementing reactive glue with hand-managed subscriptions instead of
  composing a helper.
- Forgetting to dispose helper-owned subscriptions.
- Using `DerivedProperty` as an imperative setter shortcut instead of letting it
  stay source-driven.

## Related Primitives

- [Capability Families](capability-families.md)
- [FormVM](viewmodel-families/specialized/form-vm.md)
- [DiscriminatorVM](viewmodel-families/specialized/discriminator-vm.md)
