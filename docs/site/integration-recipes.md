# Integration Recipes

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

- [Avalonia](https://github.com/thekaveh/VMx/blob/main/docs/integration/avalonia.md)
- [WPF](https://github.com/thekaveh/VMx/blob/main/docs/integration/wpf.md)
- [MAUI](https://github.com/thekaveh/VMx/blob/main/docs/integration/maui.md)

### Python

- [Textual](https://github.com/thekaveh/VMx/blob/main/docs/integration/textual.md)
- [NiceGUI](https://github.com/thekaveh/VMx/blob/main/docs/integration/nicegui.md)
- [tkinter](https://github.com/thekaveh/VMx/blob/main/docs/integration/tkinter.md)

### TypeScript

- [React](https://github.com/thekaveh/VMx/blob/main/docs/integration/react.md)
- [Vue 3](https://github.com/thekaveh/VMx/blob/main/docs/integration/vue.md)
- [Svelte](https://github.com/thekaveh/VMx/blob/main/docs/integration/svelte.md)
- [SolidJS](https://github.com/thekaveh/VMx/blob/main/docs/integration/solid.md)

### Swift

- [SwiftUI](https://github.com/thekaveh/VMx/blob/main/docs/integration/swiftui.md)

## Worked Examples

- Avalonia Notes Workspace:
  [examples/csharp/avalonia/NotesShowcase/README.md](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/README.md)
- Textual Notes Workspace:
  [examples/python/textual/notes_showcase/README.md](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/README.md)
- React Notes Workspace:
  [examples/typescript/react/notes-showcase/README.md](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/README.md)
- Swift Notes Workspace:
  [examples/swift/notes-showcase/README.md](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/README.md)

## Source Index

For the full recipe table and the common adapter pattern, use
[docs/integration/README.md](https://github.com/thekaveh/VMx/blob/main/docs/integration/README.md).
