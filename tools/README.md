# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

## 1. Current

- `generate-doc-diagrams.py` — derives the root architecture and class-diagram
  HTML/SVG/PNG triplets from repository facts. Run it without arguments to
  regenerate or with `--check` to verify byte-for-byte drift.

- `docs/validate_diagrams.py` — validates the diagram registry and every
  diagram link and PNG asset that the documentation references. Run it with
  `python -m scripts.docs.validate_diagrams`; `make docs-check` includes it.

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

  # CI mode — require all five catalog-complete flavors at 100% coverage (matches
  # .github/workflows/conformance.yml)
  python3 tools/check-conformance-coverage.py \
      --require csharp --require python --require typescript --require swift --require rust
  ```

  Rust conformance coverage uses an attached doc-comment marker:

  ```rust
  /// LIFE-001 — construct transitions
  #[test]
  fn life_001_constructs() {}
  ```

  The ID must be the first token after `///`, followed by an em dash on the same
  line, and the doc block must attach to a live `#[test]` function. Additional
  doc-comment and attribute lines may appear between the marker and function.
  Ordinary comments, file summaries, unattached markers, and markers inside
  block-commented tests do not count. Repeated IDs are deduplicated as one
  coverage claim; `--require rust` reports each missing catalog ID and exits 1.

  Unit tests live in `tools/tests/`. Run with:

  ```bash
  uv --project langs/python run pytest tools/tests/
  ```

- `check-python-fixture-sync.py` — verifies the Python package's tracked runtime
  lifecycle fixture and the sdist's four conformance fixtures are byte-identical
  to their spec sources. This keeps both runtime and shipped source tests
  self-contained.

- `check-rust-fixture-sync.py` — verifies the Rust crate's runtime lifecycle
  fixture and packaged conformance fixtures are byte-identical to their spec
  sources. The packaged-consumer smoke then runs the extracted crate's own tests.

- `check-release-please-state.py` — compares the Python source version with the
  truthful last-published release-please manifest. The `release-please` workflow uses
  its output to pause automation when a bootstrap release is pending, preventing a
  generated version downgrade.

- `check-swift-fixture-sync.py` — verifies Swift's four bundled JSON resources
  are byte-identical to `spec/fixtures/*.json`.

- `swift-test-watchdog.py` — runs a SwiftPM test command and watches the
  `xctest` process that `swift test --parallel` starts for each case. A case
  that outlives `--per-test-timeout` is sampled, killed, and reported by name,
  so a hang fails within minutes instead of at the job timeout. `--timeout`
  bounds the whole command. The Swift `examples` job runs the NotesShowcase
  tests through it.

- `select-csharp-release.py` — maps the three collision-free stable C# tag
  namespaces to exactly one package ID, verifies that package's project version,
  and writes the single-entry artifact manifest consumed by `release.yml`.

### 1.1 Release, package, and coverage checks

- `check-cobertura-threshold.py` — Fails when aggregate Cobertura line or branch coverage drops below a floor (C# coverage gate).
- `check-conformance-execution.py` — Checks that every library conformance ID has a passing executed test case, not only a marker.
- `check-coverage-floor.py` — Checks an llvm-cov coverage export against a flavor's recorded floor in `coverage-floors.json` (Rust and Swift).
- `check-fixture-contracts.py` — Validates the canonical fixture inventories and their structural contracts.
- `check-nuget-package.py` — Validates the VMx NuGet main and symbol packages against an exact contract.
- `check-python-interpreter.py` — Asserts the interpreter identity, then runs Python arguments with that executable.
- `check-python-package.py` — Validates the exact VMx Python wheel and sdist contents before publication.
- `check-react-package.py` — Fails when the React adapter's npm payload drifts from its allowlist.
- `check-rust-doc-snippets.py` — Compiles every Rust fence in the public Rust getting-started guide.
- `check-rust-package.py` — Verifies the exact allowlisted contents of the Rust crate package.
- `check-swift-package-sync.py` — Verifies that the root and nested SwiftPM manifests stay equivalent.
- `check-typescript-package.py` — Verifies the exact allowlisted contents of the TypeScript npm package.
- `check-typescript-schema-sync.py` — Asserts that TypeScript's tracked conformance schema copies match the spec.
- `check-version-consistency.py` — Cross-checks manifest versions, the compatibility matrix, changelog sections, and git tags; `--release-tag` adds the release preflight.
- `check-workflow-pins.py` — Verifies immutable GitHub Action pins and their maintenance-ledger inventory.
- `compare-benchmarks.py` — Compares two benchmark reports and flags cases outside the noise band.
- `compare-coverage-runs.py` — Compares llvm-cov exports of repeated runs and lists where their coverage differs.
- `coverage-floors.json` — Recorded Rust and Swift coverage floors read by `check-coverage-floor.py`.
- `ensure-release-changelog-unreleased.py` — Restores the canonical Unreleased section after Release Please runs.
- `extract-release-notes.awk` — Extracts one changelog section for a flavor's GitHub Release (Python, TypeScript, React, Rust, Swift).
- `render-csharp-release-notes.py` — Renders C# GitHub Release notes from a selected-package manifest.
- `smoke-npm-consumer.py` — Installs and verifies `@thekaveh/vmx` from a local tarball or the public npm registry.
- `smoke-nuget-consumer.py` — Builds clean VMx consumers from local packages or the public NuGet feed.
- `smoke-react-consumer.py` — Packs core and the React adapter and verifies a fresh ESM/CJS SSR consumer.
- `smoke-rust-consumer.py` — Builds and runs VMx from a local `.crate` or the public crates.io registry.
- `smoke-swiftpm-consumer.py` — Resolves and runs VMx from a fresh public SwiftPM consumer package.

## 2. Pure-VM contract checks (notes-showcase)

Four lint-style scripts that lock in the Pure-VM contract and the
cross-flavor parity of the flagship notes-showcase apps under
`examples/<lang>/`. Each is
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
`examples/typescript/react/notes-showcase/eslint.config.js` —
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
