# Swift Notes Workspace

SwiftUI + Combine implementation of the VMx Notes Workspace flagship scenario.
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
swift test
```

`swift test` requires XCTest from a full Xcode installation. CI runs the Swift
library and example on `macos-latest`.

## 3. Scenario Contract

This app implements the same language-neutral Notes Workspace contract as the
C# Avalonia, Python Textual, and TypeScript React flagships. See
[`../../notes-showcase-parity.md`](../../notes-showcase-parity.md) for the
cross-flavor matrix.
