# Notes Workspace — cross-flavor parity matrix

The Notes Workspace is the VMx flagship UI example portfolio: one scenario
(`spec/proposals/2026-05-29-notes-showcase-scenario.md`), implemented by the
UI-backed flavors through one language-neutral VM API. This document is the
single-page proof that every spec feature in scope is exercised by every
UI-backed flavor.

Published walkthroughs:
[Notes Workspace](../docs/content/examples/notes-workspace.md),
[VM layer map](../docs/content/examples/notes-workspace-vm-layer.md).

## 1. VM hierarchy

The diagram below is the canonical visual of the example's VM tree —
derived from the scenario contract, so it applies identically to all four
flagship implementations (names appear in their language-neutral form per
ADR-0006). The same diagram is linked from each flavor's NotesShowcase
README.

![Notes-Showcase VM hierarchy](assets/notes-showcase-vm-hierarchy.svg)

The diagram source is at
[`assets/notes-showcase-vm-hierarchy.svg`](assets/notes-showcase-vm-hierarchy.svg);
a browsable HTML version with summary cards is at
[`assets/notes-showcase-vm-hierarchy.html`](assets/notes-showcase-vm-hierarchy.html),
and a high-resolution PNG export is at
[`assets/notes-showcase-vm-hierarchy.png`](assets/notes-showcase-vm-hierarchy.png).

The companion VMx component map shows which framework primitive each example
VM composes: [`assets/notes-showcase-vmx-components.svg`](assets/notes-showcase-vmx-components.svg),
[`assets/notes-showcase-vmx-components.html`](assets/notes-showcase-vmx-components.html),
and [`assets/notes-showcase-vmx-components.png`](assets/notes-showcase-vmx-components.png).

## 2. Flavors

- **C# / Avalonia 11 on .NET 8** — `examples/csharp/avalonia/NotesShowcase/`
- **Python / Textual ≥ 0.80** — `examples/python/textual/notes_showcase/`
- **TypeScript / React 18 + Vite** — `examples/typescript/react/notes-showcase/`
- **Swift / SwiftUI + Combine (macOS)** — `examples/swift/notes-showcase/` (ADR-0067)

Each column reports whether the indicated flavor implements the VM/spec surface
and wires it into the flagship host. `Yes` means the feature is represented in
the flavor's VM/model tests and host integration; view-purity enforcement is
covered by the dedicated C#, Python, and React tooling, while Swift's core/view
split is enforced by SwiftPM target boundaries.

| #   | Spec feature (chapter / capability)                   | C# / Avalonia | Python / Textual | TypeScript / React | Swift / SwiftUI |
| --- | ----------------------------------------------------- | ------------- | ---------------- | ------------------ | --------------- |
| 1   | `HierarchicalVM` (ch. 18) — notebooks tree[^hier]     | Yes           | Yes              | Yes                | Yes             |
| 2   | `CompositeVM.Current` (ch. 6) — notes selection[^current] | Yes       | Yes              | Yes                | Yes             |
| 3   | `ComponentVM<M>` modeled (ch. 5) — `NoteVM`/`NotebookVM` | Yes        | Yes              | Yes                | Yes             |
| 4   | `FormVM` snapshot/revert/validation (ch. 20) — note editor with title errors | Yes | Yes | Yes | Yes |
| 5   | `DerivedProperty` (ch. 15) — status bar, `isDirty`, capability actions | Yes | Yes      | Yes                | Yes             |
| 6   | `RelayCommand` + `AsyncRelayCommand` reactive `canExecute` (ch. 4) — persistence-backed workspace, notebook, form, capability, Save, and Delete actions are awaitable; repository failures remain observable and success notifications follow persistence | Yes | Yes | Yes | Yes |
| 7   | `SearchableState` + `IFilterable<TItem>` (§14.5-14.6) — title search + starred filter | Yes | Yes | Yes | Yes |
| 8   | `IPageable` + `PagedComposition` (§14.10, ch. 21) — notes pagination | Yes | Yes           | Yes                | Yes             |
| 9   | `INotificationHub` + `NotificationVM` (ch. 16) — toast region | Yes   | Yes              | Yes                | Yes             |
| 10  | Async `construct()` + dispatcher (ch. 2, 11) — workspace load + notebook switch + save[^dispatcher] | Yes | Yes | Yes | Yes |
| 11  | `TreeStructureChangedMessage` (ch. 18) — add notebook re-publishes tree | Yes | Yes           | Yes                | Yes             |
| 12  | `ConfirmationDecoratorCommand` (ch. 4) — delete confirm | Yes         | Yes              | Yes                | Yes             |
| 13  | `IDialogService` (ch. 19) — export → save-file dialog | Yes           | Yes              | Yes                | Yes             |
| 14  | Capability-aware UI (§14.4) — capability action bar[^readonly] | Yes   | Yes              | Yes                | Yes             |
| 15  | `AggregateVM6` (ch. 8 — new in 2.2.0) — `WorkspaceVM` composes 6 children | Yes | Yes         | Yes                | Yes             |
| 16  | `ThemeVM` scenario contract (proposal 2026-06-02, v2.4.0) — palette + accent + font scale + high contrast as a VM[^theme] | Yes | Yes | Yes | Yes |
| 17  | `TokenPagedComposition` (ch. 21) — global all-notes search with forward tokens | Yes | Yes | Yes | Yes |
| 18  | `DiscriminatorVM` (ch. 22) — edit/preview note editor mode | Yes | Yes | Yes | Yes |
| 19  | `SearchableState<string>` — workspace tag autocomplete in `NoteFormVM` | Yes | Yes | Yes | Yes |

[^theme]: ThemeVM ships in each flavor's `viewmodels/` plus a per-framework
    `ThemeAdapter` in `views/adapter/`. `WorkspaceVM` owns the `ThemeVM` as a
    sibling of its six aggregate children, and the host binds the adapter to that
    workspace-owned instance. Composition as a 7th aggregate child remains
    **deferred** pending an `AggregateVM7` core-library extension — see
    `spec/proposals/2026-06-02-theme-vm-scenario.md` §8 and ADR-0036 §2.C / §4
    decision #3. The `THEME-001..005` scenario IDs are tested in
    `examples/<lang>/.../tests/` (not in `langs/<flavor>/tests/conformance/`)
    and are exempt from the library-coverage gate via the `_SCENARIO_PREFIXES`
    set in `tools/check-conformance-coverage.py`.

[^readonly]: The core capability action bar (CRUD capability dispatch +
    `DerivedProperty`-driven enablement) ships in all four UI-backed examples. Each
    `CapabilityActionsVM` also exposes the host-gated add-note command backed by
    the notebook read-only flag, with seed coverage and VM tests so the command
    disables consistently when the focused notebook is read-only.

[^current]: The four flagships store their notes list differently and drive
    selection through an app-owned `current` slot rather than literally through
    `CompositeVM.Current`: C# and Swift keep notes in a `CompositeVM<NoteVM>`
    used as storage, Python over an `ObservableList`, TypeScript over a plain
    array; each exposes its own `current`/`Current` property plus a selection
    command. The observable selection contract (single current, change
    notification, clear-on-delete) is identical across flavors and covered by the
    `tests/viewmodels/` suites; the `CompositeVM.Current` primitive itself is
    exercised directly by the library conformance corpus (COMP-006/010/025).

[^dispatcher]: The async-`construct()` marshalling half of this row is wired to a
    live UI dispatcher only in C# (`AvaloniaDispatcher`, Avalonia's global UI
    thread) and Swift (`DefaultDispatcher`). The React and Textual flagships
    ship a purpose-built adapter (`ReactDispatcher` asap-microtask,
    `TextualDispatcher` AsyncIO) exercised by the `views/adapter/` unit tests, but
    their composition roots build the VM tree on the synchronous immediate
    dispatcher so `constructAsync()` completes before the first paint (avoiding a
    render-before-construct flicker). Wire the shipped adapter when foreground
    marshalling onto the framework loop is desired.

## 3. Reading the matrix

- **Parity is enforced.** The C#, Python, and TypeScript flagships each ship a
  `tests/views/` headless smoke test that boots the app and asserts the main
  view rendered; Swift enforces the same core/view split via SwiftPM target
  boundaries instead (its SwiftUI `NotesShowcase` target needs Xcode, so it has
  no headless view smoke test — see §2). All four ship per-VM unit tests under
  `tests/viewmodels/` (Swift: `Tests/NotesShowcaseTests/`) mirroring the VM API.
  The Pure-VM contract checks (`tools/check-*-views.*`) keep view code
  declarative so these `Yes` entries are not load-bearing on incidental view-side
  state.
- **`AggregateVM6` (row 15)** is the spec extension this portfolio drove —
  added via ADR-0034 as a non-breaking minor bump (`spec-v2.2.0`) so that
  `WorkspaceVM` could compose its six heterogeneous children without a
  synthetic chrome wrapper.
- **Swift / SwiftUI binding bridge.** The Swift flagship uses a net-new
  Combine→SwiftUI bridge (`BindableVM`/`BindableCollection`/`BindableCommand`/
  `BindableDerived` + `ThemeAdapter`) that is not part of the library (ADR-0036
  "no new core types"); it is contained entirely in the `NotesShowcase` app
  target. Views use `@StateObject`/`@ObservedObject` + live VM getters. The
  `NotesShowcaseCore` target (pure VM layer, no SwiftUI) is
  CommandLineTools-buildable; the `NotesShowcase` and `NotesShowcaseTests`
  targets require macOS + Xcode. CI compiles the complete flagship with Swift's
  complete strict-concurrency diagnostics promoted to errors; post-await
  observable mutations return through the injected foreground dispatcher.
- **Screenshots.** Reference screenshots are owner-driven and pending. Once
  captured they will live under `assets/notes-showcase/` — one PNG per
  flavor, captured manually from each running app.

[^hier]: All four UI-backed examples implement an equivalent flat-collection +
    parent-id navigation pattern instead of subclassing
    `HierarchicalVM<TModel, TVM>` directly, because the canonical class
    sources each node's children from a per-node factory (materialized
    lazily on first access, not eagerly) — an awkward fit for a flat,
    freely-mutated `parent_id` collection. The observable contract —
    `TreeStructureChangedMessage` emission on add/remove, `current`
    selection, and `walk()` / `childrenOf()` accessors — is preserved
    identically across all four UI-backed examples, so capability dispatch and
    spec-level tree messaging behave the same way as a canonical
    `HierarchicalVM`. Per-flavor source notes:
    `examples/csharp/avalonia/NotesShowcase/ViewModels/NotebooksRootVM.cs`,
    `examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/notebooks_root_vm.py`,
    `examples/typescript/react/notes-showcase/src/viewmodels/notebooksRootVM.ts`,
    and
    `examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NotebooksRootVM.swift`.

## 4. Cross-references

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- ADR-0034: [`spec/ADRs/0034-aggregate-vm6.md`](../spec/ADRs/0034-aggregate-vm6.md)
- ADR-0067: [`spec/ADRs/0067-swift-notes-showcase-flagship.md`](../spec/ADRs/0067-swift-notes-showcase-flagship.md) — Swift flagship decision record
- Per-flavor READMEs:
  [`examples/csharp/avalonia/NotesShowcase/README.md`](csharp/avalonia/NotesShowcase/README.md),
  [`examples/python/textual/notes_showcase/README.md`](python/textual/notes_showcase/README.md),
  [`examples/typescript/react/notes-showcase/README.md`](typescript/react/notes-showcase/README.md),
  [`examples/swift/notes-showcase/README.md`](swift/notes-showcase/README.md)
