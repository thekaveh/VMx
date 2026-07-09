# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

## 1. Current

- `check-conformance-coverage.py` — parses `spec/12-conformance.md` for the catalog
  of `XXX-NNN` conformance IDs and walks each active language's registered conformance
  test directory for matching tests. The exact directories are registered in the
  `_SCRAPERS` dictionary at the top of `tools/check-conformance-coverage.py`; running
  the tool prints the discovered paths per language. Reports gaps to stdout and exits
  non-zero if any language passed via `--require` has gaps. Used by the `conformance`
  CI workflow.

  ```bash
  # report-only
  python3 tools/check-conformance-coverage.py

  # CI mode — require all five full-parity flavors at 100% coverage (matches
  # .github/workflows/conformance.yml)
  python3 tools/check-conformance-coverage.py \
      --require csharp --require python --require typescript --require swift --require rust
  ```

  Unit tests live in `tools/tests/`. Run with:

  ```bash
  uv --project langs/python run pytest tools/tests/
  ```

- `check-python-fixture-sync.py` — verifies the Python package's tracked runtime
  copy of `lifecycle-transitions.json` is byte-identical to the spec fixture.
  This keeps the package buildable from both the live checkout and the published
  sdist.

- `check-swift-fixture-sync.py` — verifies Swift's four bundled JSON resources
  are byte-identical to `spec/fixtures/*.json`.

## 2. Pure-VM contract checks (notes-showcase, Phase 6)

Four lint-style scripts that lock in the §6.1 Pure-VM contract and the
cross-flavor parity of the `examples/notes-showcase` apps. Each is
self-contained, runs from the repo root with no required arguments, and
exits 0 on success / non-zero with a per-line violation report on failure.

- `check-axaml-codebehind.py` — Avalonia view code-behind (`*.axaml.cs`)
  may only call `InitializeComponent()` or `AvaloniaXamlLoader.Load(this)`.
  Excludes `Views/Adapter/` (binding helpers, not views).

- `check-textual-views.py` — Textual widget classes may define only
  `__init__` / `compose` / `on_mount` / `render`, `action_*` methods
  (≤ 1 statement each), and `on_*` event handlers (≤ 1 statement, no
  direct hub subscriptions). Excludes `views/adapter/**`.

- `check-layer-imports.py` — enforces the layered import direction for
  the C#, Python, and TypeScript flagship examples:

  Models → Models only
  ViewModels → Models + ViewModels (plus the `Views.Adapter` sub-layer,
  which is treated as a peer because frameworks like Avalonia need
  INPC-aware sidecars co-located with the VM).
  Views → anywhere.

  The Swift flagship is intentionally outside this script: its core/view split
  is enforced by SwiftPM target boundaries (`NotesShowcaseCore` vs
  `NotesShowcase`) plus Swift compile checks.

- `check-showcase-parity.py` — verifies each flavor ships the eleven
  canonical VM test files (`workspace_vm`, `notebooks_root_vm`,
  `notebook_vm`, `notes_view_vm`, `note_vm`, `note_form_vm`,
  `status_bar_vm`, `notifications_vm`, `capability_actions_vm`,
  `theme_vm`, `in_memory_repository`) and all five `THEME-001..005`
  scenario markers.

A fifth check is the React ESLint rule under
`examples/typescript/react/notes-showcase/.eslintrc.cjs` —
`no-restricted-imports` on `src/views/components/**/*.{ts,tsx}` blocks
`useState` and `useReducer`, steering authors to the adapter hooks
(`useVm`, `useCommand`, `useDerivedProperty`).

Run all five from the repo root:

```bash
python3 tools/check-axaml-codebehind.py
python3 tools/check-textual-views.py
python3 tools/check-layer-imports.py
python3 tools/check-showcase-parity.py
( cd examples/typescript/react/notes-showcase && npm exec --no -- eslint src/views/components )
```

<!-- Future tooling ideas (matrix generator, spec-to-docs renderer) are tracked as
GitHub issues rather than carried inline here, so this README stays a description
of what exists rather than what might exist someday. -->
