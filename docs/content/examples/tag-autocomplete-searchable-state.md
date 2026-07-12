# 8.8. Tag Autocomplete & SearchableState

The note form's tag suggestions are the smallest high-signal example of
`SearchableState<T>` in the flagship portfolio.

## Current Scenario Use

- the workspace maintains the available tag set
- `NoteFormVM` composes `SearchableState<string>` over that tag list
- the tag-list mutation signal is supplied to `SearchableState`, so additions,
  removals, replacements, and resets refresh suggestions without changing the
  user's current term
- the host adapter binds the filtered suggestions without moving search state
  into the view

## Why It Matters

This example complements the broader notes-list filtering story. The notes list
uses `SearchableState` over note VMs; tag autocomplete shows the same helper on
a lightweight string collection.

If suggestions also depend on mutable state inside tag viewmodels, map an
`AggregateChangeStream` to the search source signal. The aggregate owns dynamic
member observation; search owns only its subscription to the resulting pulse.

## Where To Verify

- Primitive guide:
  [State & Reactive Helpers](../primitives/state-reactive-helpers.md)
- Parity matrix row:
  [examples/notes-showcase-parity.md](../../../examples/notes-showcase-parity.md)
- Flavor READMEs:
  [C#](../../../examples/csharp/avalonia/NotesShowcase/README.md),
  [Python](../../../examples/python/textual/notes_showcase/README.md),
  [TypeScript](../../../examples/typescript/react/notes-showcase/README.md),
  [Swift](../../../examples/swift/notes-showcase/README.md)
