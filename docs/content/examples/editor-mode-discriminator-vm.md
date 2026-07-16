# 8.7. Editor Mode & DiscriminatorVM

The note editor shows the current `DiscriminatorVM` use case in the example
portfolio: one editor surface, multiple active modes.

## 8.7.1. Current Scenario Use

All four flagship flavors use `DiscriminatorVM` to switch the note form between
edit and preview modes while keeping the surrounding workflow stable.

## 8.7.2. Why It Matters

- mode changes are explicit VM state rather than ad hoc view flags
- command enablement and derived labels stay attached to the VM layer
- the host adapter only binds current mode and visible child surface

## 8.7.3. Where To Verify

- Primitive guide:
  [DiscriminatorVM](../primitives/viewmodel-families/specialized/discriminator-vm.md)
- Parity matrix row:
  [examples/notes-showcase-parity.md](../../../examples/notes-showcase-parity.md)
- Flavor READMEs:
  [C#](../../../examples/csharp/avalonia/NotesShowcase/README.md),
  [Python](../../../examples/python/textual/notes_showcase/README.md),
  [TypeScript](../../../examples/typescript/react/notes-showcase/README.md),
  [Swift](../../../examples/swift/notes-showcase/README.md)
