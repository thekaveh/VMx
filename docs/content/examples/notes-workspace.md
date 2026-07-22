# 8.3. Notes Workspace

Notes Workspace is the flagship VMx example portfolio: one scenario, four
idiomatic hosts, and one shared VM contract.

<img src="../../assets/diagrams/examples-vm-layer.svg" alt="Examples VM Layer Map" class="vmx-diagram" />

<p>
  <a href="notes-workspace-vm-layer/">Open the VM layer walkthrough</a>
  &middot;
  <a href="../../assets/diagrams/examples-vm-layer.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/examples-vm-layer.png">PNG</a>
</p>

## 8.3.1. Canonical Sources

- Cross-flavor parity matrix:
  [examples/notes-showcase-parity.md](../../../examples/notes-showcase-parity.md)
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

The portfolio is the working example for the four current UI-backed flagship hosts:

- notebook tree projection representing the `HierarchicalVM` capability
- selectable notes list through `CompositeVM.current`
- strict `FormVM` editing and validation
- `DerivedProperty` status and enablement
- `SearchableState`, paged notes, and token-paged global search
- dialogs, notifications, confirmation flows, and theme state
- edit/preview mode with `DiscriminatorVM`

## 8.3.4. Important Modeling Note

The notebooks tree in the current flagship apps is not built from direct
`HierarchicalVM` subclasses. All four UI-backed examples use flat `ComponentVM`-based
adapters that represent the `HierarchicalVM` capability and preserve the same
tree messaging contract.

Use the parity matrix for the exact row-by-row feature coverage, then drill into
the flavor README you care about for project layout and run commands.

## 8.3.5. Swift Foreground Contract

The Swift flagship uses VMx's `DefaultDispatcher` in production. Persistence
and notification awaits may resume on any executor, but observable collection,
selection, form, and command-state mutations complete through an awaited
foreground-dispatch bridge. Its CI build enables complete strict-concurrency
checking and promotes every concurrency warning to an error for both the VMx
package and the full SwiftUI flagship.

## 8.3.6. Locale Scope

Notes Workspace is intentionally an en-US reference scenario. All hosts use
the same English labels, seed content, validation messages, and notifications;
the parity matrix therefore makes no translated-catalog claim. VMx still
provides the injectable localization hook described in
[spec chapter 17](../../../spec/17-localization.md), with behavior verified by
the library conformance suites. Applications that need multiple locales supply
their own host-native catalog adapter.
