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

- macOS with Xcode for `swift test` and the SwiftUI app target.
- Command Line Tools are enough for `swift build` of the core package.

## 2. Build And Test

```bash
cd examples/swift/notes-showcase
swift build
swift build -c release \
  -Xswiftc -strict-concurrency=complete \
  -Xswiftc -warn-concurrency \
  -Xswiftc -warnings-as-errors
swift test
```

`swift test` requires XCTest from a full Xcode installation. CI runs the Swift
library and example on `macos-15`, including the strict-concurrency build.

## 3. Scenario Contract

This app implements the same language-neutral Notes Workspace contract as the
C# Avalonia, Python Textual, and TypeScript React flagships. See
[`../../notes-showcase-parity.md`](../../notes-showcase-parity.md) for the
cross-flavor matrix, the
[`../../assets/notes-showcase-vm-hierarchy.svg`](../../assets/notes-showcase-vm-hierarchy.svg)
hierarchy diagram, and the
[`../../assets/notes-showcase-vmx-components.svg`](../../assets/notes-showcase-vmx-components.svg)
VMx component map.

## 4. Feature Traceability

The Swift port mirrors the 19-row flagship surface: strict `FormVM` editing
with title validation, `DerivedProperty` status/readiness labels, paged notes,
token-paged global search, notification/dialog flows, capability actions,
theme state, edit/preview mode through `DiscriminatorVM`, and tag suggestions
through `SearchableState<String>`. Core VM code lives under
`Sources/NotesShowcaseCore/ViewModels/`; SwiftUI projections live under
`Sources/NotesShowcase/Views/`.

## 5. Foreground Execution

The production composition root uses VMx's `DefaultDispatcher`. Async VM
operations await persistence away from the UI and then use the dispatcher-backed
foreground bridge for observable collection, selection, form, and command-state
mutations. Notification posts are awaited directly. This keeps UI state on the
host's foreground executor without imposing `MainActor` on language-neutral VMx
capability protocols.
