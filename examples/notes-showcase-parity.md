# Notes Workspace — cross-flavor parity matrix

The Notes Workspace is the VMx flagship example portfolio: one scenario
(`spec/proposals/2026-05-29-notes-showcase-scenario.md`), three idiomatic
implementations sharing one language-neutral VM API. This document is the
single-page proof that every spec feature in scope is exercised by every
flavor.

- **C# / Avalonia 11 on .NET 8** — `examples/csharp/avalonia/NotesShowcase/`
- **Python / Textual ≥ 0.80** — `examples/python/textual/notes_showcase/`
- **TypeScript / React 18 + Vite** — `examples/typescript/react/notes-showcase/`

Each column reports whether the indicated flavor exercises the indicated VMx
spec feature inside its `viewmodels/` layer and surfaces it through its
`views/` layer (including the bridge adapter under `views/adapter/`). A `✓`
means the feature is wired end-to-end — VM emits, adapter forwards, view
renders, headless smoke covers it.

| #   | Spec feature (chapter / capability)                   | C# / Avalonia | Python / Textual | TypeScript / React |
| --- | ----------------------------------------------------- | ------------- | ---------------- | ------------------ |
| 1   | `HierarchicalVM` (ch. 18) — notebooks tree            | ✓             | ✓                | ✓                  |
| 2   | `CompositeVM.Current` (ch. 6) — notes selection       | ✓             | ✓                | ✓                  |
| 3   | `ComponentVM<M>` modeled (ch. 5) — `NoteVM`/`NotebookVM` | ✓          | ✓                | ✓                  |
| 4   | `FormVM` snapshot/revert (ch. 20) — note editor       | ✓             | ✓                | ✓                  |
| 5   | `DerivedProperty` (ch. 15) — status bar, `isDirty`, capability actions | ✓ | ✓        | ✓                  |
| 6   | `RelayCommand` reactive `canExecute` (ch. 4) — Save / Revert / Delete | ✓ | ✓         | ✓                  |
| 7   | `SearchableState` + `IFilterable<T>` (§14.5–14.6) — title search + starred filter | ✓ | ✓ | ✓               |
| 8   | `IPageable` + `PagedComposition` (§14.10, ch. 21) — notes pagination | ✓ | ✓             | ✓                  |
| 9   | `INotificationHub` + `NotificationVM` (ch. 16) — toast region | ✓     | ✓                | ✓                  |
| 10  | Async `construct()` + dispatcher (ch. 2, 11) — workspace load + notebook switch + save | ✓ | ✓ | ✓        |
| 11  | `TreeStructureChangedMessage` (ch. 18) — add notebook re-publishes tree | ✓ | ✓             | ✓                  |
| 12  | `ConfirmationDecoratorCommand` (ch. 4) — delete confirm | ✓           | ✓                | ✓                  |
| 13  | `IDialogService` (ch. 19) — export → save-file dialog | ✓             | ✓                | ✓                  |
| 14  | Capability-aware UI (§14.4) — capability action bar   | ✓             | ✓                | ✓                  |
| 15  | `AggregateVM6` (ch. 8 — new in 2.2.0) — `WorkspaceVM` composes 6 children | ✓ | ✓           | ✓                  |

## Reading the matrix

- **Parity is enforced.** Each flavor ships a `tests/views/` headless smoke
  test that boots the app and asserts the main view rendered, plus per-VM
  unit tests under `tests/viewmodels/` mirroring the VM API. The Pure-VM
  contract checks (`tools/check-*-views.*`) keep view code declarative so
  these `✓` marks are not load-bearing on incidental view-side state.
- **`AggregateVM6` (row 15)** is the spec extension this portfolio drove —
  added via ADR-0034 as a non-breaking minor bump (`spec-v2.2.0`) so that
  `WorkspaceVM` could compose its six heterogeneous children without a
  synthetic chrome wrapper.
- **Screenshots.** Reference screenshots live in
  [`assets/notes-showcase/`](../assets/notes-showcase/) (one PNG per flavor,
  captured manually).

## Cross-references

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- ADR-0034: [`spec/ADRs/0034-aggregate-vm6.md`](../spec/ADRs/0034-aggregate-vm6.md)
- Per-flavor READMEs:
  [`examples/csharp/avalonia/NotesShowcase/README.md`](csharp/avalonia/NotesShowcase/README.md),
  [`examples/python/textual/notes_showcase/README.md`](python/textual/notes_showcase/README.md),
  [`examples/typescript/react/notes-showcase/README.md`](typescript/react/notes-showcase/README.md)
