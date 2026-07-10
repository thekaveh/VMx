# 9. Integration Recipes

The repo already carries framework-specific integration notes under
`docs/integration/`. This page is the site-level router for those recipes, not a
duplicate cookbook.

## What The Recipes Cover

Each recipe summarizes the same adapter problem:

- bridge VMx property-change events into the host framework's reactivity model
- route host actions back into `RelayCommand` or related command surfaces
- keep collection updates and dispatcher marshalling inside the adapter boundary

## Current Recipes

### C\#

- [Avalonia](../integration/avalonia.md)
- [WPF](../integration/wpf.md)
- [MAUI](../integration/maui.md)

### Python

- [Textual](../integration/textual.md)
- [NiceGUI](../integration/nicegui.md)
- [tkinter](../integration/tkinter.md)

### TypeScript

- [React](../integration/react.md)
- [Vue 3](../integration/vue.md)
- [Svelte](../integration/svelte.md)
- [SolidJS](../integration/solid.md)

### Swift

- [SwiftUI](../integration/swiftui.md)

## Worked Examples

- Avalonia Notes Workspace:
  [examples/csharp/avalonia/NotesShowcase/README.md](../../examples/csharp/avalonia/NotesShowcase/README.md)
- Textual Notes Workspace:
  [examples/python/textual/notes_showcase/README.md](../../examples/python/textual/notes_showcase/README.md)
- React Notes Workspace:
  [examples/typescript/react/notes-showcase/README.md](../../examples/typescript/react/notes-showcase/README.md)
- Swift Notes Workspace:
  [examples/swift/notes-showcase/README.md](../../examples/swift/notes-showcase/README.md)

## Source Index

For the full recipe table and the common adapter pattern, use
[docs/integration/README.md](../integration/README.md).
