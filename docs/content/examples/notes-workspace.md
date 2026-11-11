# 8.3. Notes Workspace

Notes Workspace is the flagship VMx example portfolio: one scenario, four
idiomatic hosts, and one shared VM contract. The
[VM Layer Map](notes-workspace-vm-layer.md) shows how the scenario composes VMx
primitives.

## 8.3.1. Canonical Sources

- Cross-flavor parity matrix:
  [examples/notes-showcase-parity.md](../../../examples/notes-showcase-parity.md)
- Shared behavioral scenarios, asserted by all four flagship suites:
  [examples/notes-showcase-scenario.json](../../../examples/notes-showcase-scenario.json)
  (workspace lifecycle) and
  [examples/notes-showcase-theme-scenario.json](../../../examples/notes-showcase-theme-scenario.json)
  (`THEME-001`..`THEME-005`)
- VM hierarchy diagram source:
  [examples/assets/notes-showcase-vm-hierarchy.svg](../../../examples/assets/notes-showcase-vm-hierarchy.svg)
- Scenario proposal:
  [spec/proposals/2026-05-29-notes-showcase-scenario.md](../../../spec/proposals/2026-05-29-notes-showcase-scenario.md)

## 8.3.2. Flavor Hosts

Start these commands from the repository root:

| Host               | Command                                                                            |
| ------------------ | ---------------------------------------------------------------------------------- |
| C# / Avalonia      | `dotnet run --project examples/csharp/avalonia/NotesShowcase`                      |
| Python / Textual   | `uv run --project examples/python/textual/notes_showcase python -m notes_showcase` |
| TypeScript / React | `cd examples/typescript/react/notes-showcase && npm ci && npm run dev`             |
| Swift / SwiftUI    | `cd examples/swift/notes-showcase && swift build && swift test`                    |

The React command builds the local VMx package and then serves the app at
`http://localhost:5173`. The Swift command builds and tests the package on
macOS. `swift test` and the SwiftUI app target need a full Xcode installation.

Each host README gives the project layout, the tests, and the other commands:

- C# / Avalonia:
  [examples/csharp/avalonia/NotesShowcase/README.md](../../../examples/csharp/avalonia/NotesShowcase/README.md)
- Python / Textual:
  [examples/python/textual/notes_showcase/README.md](../../../examples/python/textual/notes_showcase/README.md)
- TypeScript / React:
  [examples/typescript/react/notes-showcase/README.md](../../../examples/typescript/react/notes-showcase/README.md)
- Swift / SwiftUI:
  [examples/swift/notes-showcase/README.md](../../../examples/swift/notes-showcase/README.md)

## 8.3.3. What It Exercises

The portfolio is the working example for the four UI-backed flagship hosts:

- a notebook tree with the `HierarchicalVM` tree contract
- selectable notes list through an app-owned `current` slot
- strict `FormVM` editing and validation
- `DerivedProperty` status and enablement
- `SearchableState`, paged notes, and token-paged global search
- dialogs, notifications, confirmation flows, and theme state
- edit/preview mode with `DiscriminatorVM`

## 8.3.4. Important Modeling Note

The TypeScript host builds the notebooks tree from `HierarchicalVM` nodes, with
a `TreeSelection` for the current notebook. The C#, Python, and Swift hosts use
flat `ComponentVM`-based parent-id adapters instead. These adapters keep the
same observable tree contract, including `TreeStructureChangedMessage`.

Use the parity matrix for row-by-row feature coverage.

## 8.3.5. Swift Foreground Contract

The Swift flagship uses VMx's `DefaultDispatcher` in production. Persistence
and notification awaits may resume on any executor, but observable collection,
selection, form, and command-state mutations complete through an awaited
foreground-dispatch bridge. Its CI build enables complete strict-concurrency
checking and promotes every concurrency warning to an error for both the VMx
package and the full SwiftUI flagship.

## 8.3.6. Locale Scope

Notes Workspace is an en-US reference scenario. All hosts use the same English
labels, seed content, validation messages, and notifications, so the parity
matrix makes no translated-catalog claim. VMx provides an injectable
localization hook ([spec chapter 17](../../../spec/17-localization.md)), which
the library conformance suites verify. Applications that need multiple locales
supply their own host-native catalog adapter.
