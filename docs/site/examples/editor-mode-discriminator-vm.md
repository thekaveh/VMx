# Editor Mode & DiscriminatorVM

The note editor shows the current `DiscriminatorVM` use case in the example
portfolio: one editor surface, multiple active modes.

## Current Scenario Use

All four flagship flavors use `DiscriminatorVM` to switch the note form between
edit and preview modes while keeping the surrounding workflow stable.

## Why It Matters

- mode changes are explicit VM state rather than ad hoc view flags
- command enablement and derived labels stay attached to the VM layer
- the host adapter only binds current mode and visible child surface

## Where To Verify

- Primitive guide:
  [DiscriminatorVM](../primitives/viewmodel-families/specialized/discriminator-vm.md)
- Parity matrix row:
  [examples/notes-showcase-parity.md](https://github.com/thekaveh/VMx/blob/main/examples/notes-showcase-parity.md)
- Flavor READMEs:
  [C#](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/README.md),
  [Python](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/README.md),
  [TypeScript](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/README.md),
  [Swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/README.md)
