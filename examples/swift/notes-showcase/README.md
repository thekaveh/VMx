# Swift Notes Workspace

SwiftUI + Combine implementation of the VMx Notes Workspace flagship scenario.
Architecture diagram:
[`swift-notes-showcase.svg`](../../../docs/assets/diagrams/swift-notes-showcase.svg)
([HTML](../../../docs/assets/diagrams/swift-notes-showcase.html),
[PNG](../../../docs/assets/diagrams/swift-notes-showcase.png)).
The package has three targets:

- `NotesShowcaseCore` — pure VM layer, models, messages, and repository.
- `NotesShowcase` — SwiftUI app and Combine-to-SwiftUI binding adapters.
- `NotesShowcaseTests` — scenario and VM tests, including `THEME-001..005`.

## 1. Requirements

- macOS 13 or later.
- Command Line Tools are enough for `swift build` and `swift run`. They build
  the `NotesShowcaseCore` library and the `NotesShowcase` SwiftUI app.
- `swift test` needs a full Xcode installation, because XCTest ships with
  Xcode.

## 2. Run

```bash
cd examples/swift/notes-showcase
swift run NotesShowcase
```

The app opens one window with the VMx Notes Workspace toolbar. It loads the
seed notebooks from the in-memory repository and selects the first one. Quit
the app to stop the process.

The window can open behind the terminal. If it does, click the window before
you use the keyboard shortcuts. Until then, the terminal receives the keys.

## 3. Build and test

Run these commands from `examples/swift/notes-showcase`:

```bash
swift build
swift build -c release \
  -Xswiftc -strict-concurrency=complete \
  -Xswiftc -warn-concurrency \
  -Xswiftc -warnings-as-errors
swift test
```

CI runs the Swift library and example on `macos-15`, including the
strict-concurrency build.

## 4. Keyboard shortcuts

| Shortcut      | Action                           |
| ------------- | -------------------------------- |
| `Cmd+N`       | New note in the current notebook |
| `Cmd+Shift+N` | New notebook at the root         |
| `Cmd+E`       | Export the workspace snapshot    |

The toolbar buttons in `Sources/NotesShowcase/Views/RootView.swift` declare
these shortcuts. Each button runs a VM command, and the command's `canExecute`
state enables or disables the button.

## 5. Scenario contract

This app implements the same language-neutral Notes Workspace contract as the
C# Avalonia, Python Textual, and TypeScript React flagships. See
[`../../notes-showcase-parity.md`](../../notes-showcase-parity.md) for the
cross-flavor matrix, the
[`../../assets/notes-showcase-vm-hierarchy.svg`](../../assets/notes-showcase-vm-hierarchy.svg)
hierarchy diagram, and the
[`../../assets/notes-showcase-vmx-components.svg`](../../assets/notes-showcase-vmx-components.svg)
VMx component map.

## 6. Feature traceability

The Swift port mirrors the 19-row flagship surface. It includes these
features:

- strict `FormVM` editing with title validation
- `DerivedProperty` status and readiness labels
- paged notes and token-paged global search
- notification and dialog flows
- capability actions and theme state
- edit and preview modes through `DiscriminatorVM`
- tag suggestions through `SearchableState<String>`

Core VM code lives under `Sources/NotesShowcaseCore/ViewModels/`. SwiftUI
projections live under `Sources/NotesShowcase/Views/`.

## 7. Foreground execution

The production composition root uses VMx's `DefaultDispatcher`. Async VM
operations await persistence away from the UI. Then they use the
dispatcher-backed foreground bridge for observable collection, selection, form,
and command-state mutations. Notification posts are awaited directly. Thus UI
state stays on the host's foreground executor, and the language-neutral VMx
capability protocols do not need `MainActor`.
