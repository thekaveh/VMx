# 8.9. Smaller Examples

The smaller demos are the shortest path to the builder, lifecycle, hub, and
host-adapter basics without reading the full flagship app.

For the VMx/component shape of each example, see the
[Example Diagram Gallery](example-diagram-gallery.md).

## 8.9.1. C\#

- `examples/csharp/console/HelloVMx/`:
  minimal lifecycle and hub logging
- `examples/csharp/wpf/TodoApp/`:
  WPF wrapper-and-binding example

Source index:
[examples/csharp/README.md](../../../examples/csharp/README.md)

## 8.9.2. Python

- `examples/python/console/hello_vmx/`:
  minimal lifecycle and hub logging
- `examples/python/tk/todo_app/`:
  tkinter MVVM app
- `examples/python/textual/inspector/`:
  live tree and hub inspector

Source indexes:
[examples/python/README.md](../../../examples/python/README.md),
[examples/python/textual/inspector/README.md](../../../examples/python/textual/inspector/README.md)

## 8.9.3. TypeScript

- `examples/typescript/console/hello-vmx/`:
  minimal Node-based lifecycle and hub logging

Source index:
[examples/typescript/README.md](../../../examples/typescript/README.md)

## 8.9.4. Swift

Swift currently exposes the flagship Notes Workspace example rather than a
separate small demo. Use the flavor README and SwiftUI integration recipe as the
minimum entry points:
[langs/swift/README.md](../../../langs/swift/README.md),
[SwiftUI Integration](../integration/swiftui.md)

## 8.9.5. Rust

- `examples/rust/console/hello-vmx/`:
  Cargo console demo using `ComponentVm`, `CompositeVm`, `FilteredCompositeVm`,
  and `RelayCommand`
- `examples/rust/tui/notes-showcase/`:
  Ratatui showcase using a pure VMx MVVM layer with search, paging, validation,
  notifications, and editor mode

Source index:
[examples/rust/README.md](../../../examples/rust/README.md)
