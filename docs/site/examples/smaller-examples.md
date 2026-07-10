# Smaller Examples

The smaller demos are the shortest path to the builder, lifecycle, hub, and
host-adapter basics without reading the full flagship app.

For the VMx/component shape of each example, see the
[Example Diagram Gallery](example-diagram-gallery.md).

## C\#

- `examples/csharp/console/HelloVMx/`:
  minimal lifecycle and hub logging
- `examples/csharp/wpf/TodoApp/`:
  WPF wrapper-and-binding example

Source index:
[examples/csharp/README.md](https://github.com/thekaveh/VMx/blob/main/examples/csharp/README.md)

## Python

- `examples/python/console/hello_vmx/`:
  minimal lifecycle and hub logging
- `examples/python/tk/todo_app/`:
  tkinter MVVM app
- `examples/python/textual/inspector/`:
  live tree and hub inspector

Source indexes:
[examples/python/README.md](https://github.com/thekaveh/VMx/blob/main/examples/python/README.md),
[examples/python/textual/inspector/README.md](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/inspector/README.md)

## TypeScript

- `examples/typescript/console/hello-vmx/`:
  minimal Node-based lifecycle and hub logging

Source index:
[examples/typescript/README.md](https://github.com/thekaveh/VMx/blob/main/examples/typescript/README.md)

## Swift

Swift currently exposes the flagship Notes Workspace example rather than a
separate small demo. Use the flavor README and SwiftUI integration recipe as the
minimum entry points:
[langs/swift/README.md](https://github.com/thekaveh/VMx/blob/main/langs/swift/README.md),
[docs/integration/swiftui.md](https://github.com/thekaveh/VMx/blob/main/docs/integration/swiftui.md)

## Rust

- `examples/rust/console/hello-vmx/`:
  Cargo console demo using `ComponentVm`, `CompositeVm`, `FilteredCompositeVm`,
  and `RelayCommand`
- `examples/rust/tui/notes-showcase/`:
  Ratatui showcase using a pure VMx MVVM layer with search, paging, validation,
  notifications, and editor mode

Source index:
[examples/rust/README.md](https://github.com/thekaveh/VMx/blob/main/examples/rust/README.md)
