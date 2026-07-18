# 8.1. Examples

VMx ships a small set of examples with two jobs: prove the minimal surface in
small demos and prove the full cross-language contract in the flagship Notes
Workspace portfolio.

## 8.1.1. Start Here

- [Notes Workspace](notes-workspace.md) for the full stable four-flavor scenario.
- [Example Diagram Gallery](example-diagram-gallery.md) for one generated VMx
  architecture diagram per committed example app.
- [Rust TUI Notes Showcase](rust-tui-notes-showcase.md) for the Rust-native
  full MVVM terminal example.
- [VM Layer Map](notes-workspace-vm-layer.md) when you want the component-to-VM
  mapping first.
- [Smaller Examples](smaller-examples.md) for console, WPF, tkinter, and
  inspector demos.

## 8.1.2. Current Portfolio

| Flavor     | Small demos                                          | Scenario role             |
| ---------- | ---------------------------------------------------- | ------------------------- |
| C#         | Console `HelloVMx`, WPF Todo                         | Avalonia flagship         |
| Python     | Console `hello-vmx`, tkinter Todo, Textual Inspector | Textual flagship          |
| TypeScript | Console `hello-vmx`                                  | React flagship            |
| Swift      | none beyond the flagship today                       | SwiftUI flagship          |
| Rust       | Console `hello-vmx`                                  | Reduced Ratatui companion |

## 8.1.3. Reading Strategy

- Use the smaller examples when you want the minimum lifecycle, hub, and
  builder shape.
- Use Notes Workspace when you want pagination, search, dialogs,
  notifications, theme state, or cross-flavor parity.
- Use the source READMEs for full run commands and per-project layout:
  [C# examples](../../../examples/csharp/README.md),
  [Python examples](../../../examples/python/README.md),
  [TypeScript examples](../../../examples/typescript/README.md),
  [Swift flagship](../../../examples/swift/notes-showcase/README.md),
  [Rust examples](../../../examples/rust/README.md).
- Use the in-repo generated diagram index when browsing from GitHub:
  [examples/DIAGRAMS.md](../../../examples/DIAGRAMS.md).
