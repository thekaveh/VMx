# Integration recipes

One-page sketches for wiring a VMx viewmodel into a front-end framework's
reactivity primitive. These are *not* full tutorials — they show the
minimum adapter shape and point to a fuller example (the
[Notes-Showcase](../../examples/) project where one exists, or the
matching cookbook folder under `examples/` for the existing apps).

Each recipe explains:

1. The framework's reactivity primitive.
1. How it maps to VMx's `PropertyChangedMessage` / `RelayCommand` /
   collection events.
1. A code skeleton (≤ 30 lines).
1. Where to look for fuller examples.

| Framework | Language   | Recipe                     | Worked example                                               |
| --------- | ---------- | -------------------------- | ------------------------------------------------------------ |
| WPF       | C#         | [wpf.md](wpf.md)           | `examples/csharp/wpf/TodoApp/`                               |
| MAUI      | C#         | [maui.md](maui.md)         | none yet — recipe-only                                       |
| Avalonia  | C#         | [avalonia.md](avalonia.md) | `examples/csharp/avalonia/NotesShowcase/` (Notes-Showcase)   |
| Textual   | Python     | [textual.md](textual.md)   | `examples/python/textual/inspector/` + Notes-Showcase        |
| NiceGUI   | Python     | [nicegui.md](nicegui.md)   | none yet — recipe-only                                       |
| Tkinter   | Python     | [tkinter.md](tkinter.md)   | `examples/python/tk/todo_app/`                               |
| React     | TypeScript | [react.md](react.md)       | `examples/typescript/react/notes-showcase/` (Notes-Showcase) |
| Vue 3     | TypeScript | [vue.md](vue.md)           | none yet — recipe-only                                       |
| Svelte    | TypeScript | [svelte.md](svelte.md)     | none yet — recipe-only                                       |
| SolidJS   | TypeScript | [solid.md](solid.md)       | none yet — recipe-only                                       |
| SwiftUI   | Swift      | [swiftui.md](swiftui.md)   | none yet — Swift flavor is a v2.5.0 subset (recipe-only)     |

## Common pattern

Every recipe bridges three things:

- **State.** A property on the VM whose value changes over time. VMx
  publishes `PropertyChangedMessage<TValue>(sender, propertyName, value)`
  to the message hub each time the property changes.
- **Commands.** `RelayCommand` (and friends) expose `execute` and
  `canExecute`; bind them to buttons and menu items.
- **Collections.** `ServicedObservableCollection<T>` and
  `ObservableList<T>` publish `CollectionChangedMessage` events; bind a
  list / grid widget to those.

The framework-specific adapter only needs to translate VMx's hub messages
into the framework's reactivity primitive — `INotifyPropertyChanged`,
`textual.reactive.reactive`, `useSyncExternalStore`, etc. — and route
button clicks back to `command.execute(parameter)`.

## Don't see your framework?

Open an issue or PR with a new one-page recipe following the template
above. The reference adapters in
[examples/csharp/wpf/TodoApp/](../../examples/csharp/wpf/TodoApp/) and
the Notes-Showcase Avalonia/Textual/React adapters are good models to
copy.
