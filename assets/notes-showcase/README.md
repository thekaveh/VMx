# Notes Workspace — reference screenshots

This directory hosts one PNG per flagship Notes Workspace flavor. Screenshots
are captured manually (no CI step) so the binary churn stays out of automated
runs.

| File           | Source app                                                          | Capture command                                                              |
| -------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `avalonia.png` | [`examples/csharp/avalonia/NotesShowcase/`](../../examples/csharp/avalonia/NotesShowcase/) | `dotnet run --project examples/csharp/avalonia/NotesShowcase`         |
| `textual.png`  | [`examples/python/textual/notes_showcase/`](../../examples/python/textual/notes_showcase/) | `uv run --project examples/python/textual/notes_showcase python -m notes_showcase` |
| `react.png`    | [`examples/typescript/react/notes-showcase/`](../../examples/typescript/react/notes-showcase/) | `npm run dev` from the example dir, then capture `localhost:5173`     |
| `swiftui.png`  | [`examples/swift/notes-showcase/`](../../examples/swift/notes-showcase/) | `swift run NotesShowcase` from the example dir                         |

## 1. Capture convention

1. Launch the app via the command above.
1. Wait for the workspace to finish its `construct()` (≈300 ms): the
   notebooks tree shows 4 root notebooks, the notes list shows the seed
   notes for the first notebook, and the form is bound to the first note.
1. Capture the **entire main window / TUI / browser viewport** at a 16:10
   aspect ratio (e.g. 1600×1000). PNG, no scaling.
1. Drop the PNG into this directory with the corresponding name above and
   commit it on a separate manual-screenshot PR.

The parity matrix at
[`../../examples/notes-showcase-parity.md`](../../examples/notes-showcase-parity.md)
points at this directory as the visual companion to the per-feature table.
The scenario contract at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md)
is the source of truth for what the screenshots should depict.

Capture status: all four PNGs are owner-driven and pending — PRs welcome.
