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

- notebook tree projection representing the `HierarchicalVM` capability
- selectable notes list through an app-owned `current` slot
- strict `FormVM` editing and validation
- `DerivedProperty` status and enablement
- `SearchableState`, paged notes, and token-paged global search
- dialogs, notifications, confirmation flows, and theme state
- edit/preview mode with `DiscriminatorVM`

## 8.3.4. Important Modeling Note

The flagship notebooks tree does not subclass `HierarchicalVM`. All four
UI-backed examples use flat `ComponentVM`-based adapters. These adapters
represent the `HierarchicalVM` capability and keep its tree messaging contract.

Use the parity matrix for row-by-row feature coverage. Use each flavor README
for project layout and run commands.

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
