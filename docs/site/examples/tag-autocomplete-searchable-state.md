# Tag Autocomplete & SearchableState

The note form's tag suggestions are the smallest high-signal example of
`SearchableState<T>` in the flagship portfolio.

## Current Scenario Use

- the workspace maintains the available tag set
- `NoteFormVM` composes `SearchableState<string>` over that tag list
- the host adapter binds the filtered suggestions without moving search state
  into the view

## Why It Matters

This example complements the broader notes-list filtering story. The notes list
uses `SearchableState` over note VMs; tag autocomplete shows the same helper on
a lightweight string collection.

## Where To Verify

- Primitive guide:
  [State & Reactive Helpers](../primitives/state-reactive-helpers.md)
- Parity matrix row:
  [examples/notes-showcase-parity.md](https://github.com/thekaveh/VMx/blob/main/examples/notes-showcase-parity.md)
- Flavor READMEs:
  [C#](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/README.md),
  [Python](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/README.md),
  [TypeScript](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/README.md),
  [Swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/README.md)
