# AGENTS.md

This file provides guidance to coding agents that work with code in this repository.

## 1. Architecture

VMx is **one language-neutral specification with five idiomatic flavors**. All five are catalog-complete for the library conformance IDs in `spec/12-conformance.md`. C#, Python, TypeScript, and Swift are member-aligned. Rust's recorded differences and open items are listed in the disposition of the parity ledger, `docs/maintenance/2026-07-16-rust-capability-parity.md` §12.6; ADR-0120 (sender identity) and ADR-0202 (`HierarchicalVm` node data) are its retained idioms. Naming remains idiomatic (PascalCase C#, snake_case Python and Rust methods, camelCase TypeScript and Swift — codified in `spec/ADRs/0006-idiomatic-api-per-language.md`).

- **`spec/` is the source of truth.** 24 numbered markdown chapters (`00-overview.md` … `23-async-resource-vm.md`), the ADRs indexed in `spec/ADRs/README.md`, four JSON fixtures, supporting schemas, current version in `spec/VERSION` (3.30.0). Behavior changes start here.
- **`spec/fixtures/*.json` are consumed by all flavors** for lifecycle, message-ordering, command-truthtable, and derived-property validation. Python tracks `lifecycle-transitions.json` under `langs/python/src/vmx/lifecycle/_data/` for runtime loading, and `tools/check-python-fixture-sync.py` keeps it byte-identical to the spec fixture; Rust tracks the same runtime fixture under `langs/rust/src/fixtures/` so the published crate is self-contained, and `tools/check-rust-fixture-sync.py` keeps that copy byte-identical. The other fixtures are conformance-test inputs. TypeScript copies all fixtures via `npm run sync-fixtures` (auto-run by `prebuild`, `pretest`, `pretypecheck`, `pretypecheck:tests`, and `prepack`). C# embeds `lifecycle-transitions.json` for runtime and copies all fixtures into conformance test output. Swift ships all four JSON resources under `langs/swift/Sources/VMx/Resources`, including `LifecycleTransitionTable.swift` loading `lifecycle-transitions.json` from `Bundle.module`. When editing a fixture, ensure every flavor still loads the relevant runtime/test resource.
- **`spec/12-conformance.md` enumerates the normative test IDs** — library IDs (`LIFE-001`, `HUB-013`, `CVM-010`, `SUBV-004`, `AGCH-010`, `SRCH-008`, `ARES-011`, `DISP-014`, `FORM-042`, `COL-064`, `BLD-006`, `GRP-013`, `HIER-030`, `NOTIF-020`, `COMP-045`, `DISC-006`, …) plus the `THEME-00x` scenario IDs that live in the flagship example apps. C#, Python, TypeScript, Swift, and Rust each implement every library ID under their conformance test trees. `tools/check-conformance-coverage.py` enforces 100% catalog coverage for all five flavors in CI; coverage alone does not prove member-level parity.
- **Each flavor versions independently** but a spec major bump triggers a major bump in every active flavor, and a flavor's own source-breaking change takes a flavor major bump even under a spec minor (README §6.1). Each package declares the spec version it implements: `MinSpecVersion` (C#), `__min_spec_version__` (Python), `__minSpecVersion__` (TypeScript), `VMxVersion.minSpecVersion` (Swift), `MIN_SPEC_VERSION` (Rust). Compatibility is recorded in `compatibility-matrix.md`. Release-please updates the current Python cell after its manifest matches the source version (`tools/check-release-please-state.py`). Spec and other flavor changes remain explicit edits.
- **Per-flavor source layout mirrors the spec chapters** — `aggregates/`, `builders/`, `commands/`, `components/`, `composites/`, `forwarding/`, `groups/`, `lifecycle/`, `messages/`, `services/`, `tree/`, `collections/`, `capabilities/`, `properties/` (DerivedProperty), `notifications` (opt-in package/sub-path where applicable), `localization/`, `hierarchical/`, `dialogs/`, `forms/`, and `state/` (DiscriminatorVM). When adding a primitive, add it to the same-named area in every supported flavor that ships the area.
- **Reactive primitive per flavor**: C# uses `System.Reactive`, Python uses `reactivex`, TypeScript uses `rxjs`, Swift uses `Combine` (macOS-only — no Linux CI for Swift), and Rust uses VMx-owned hot-stream facades with no third-party reactive runtime per ADR-0103. Don't introduce additional reactive libraries.
- **Known cross-flavor divergences are documented**, not accidental: Swift still traps where Swift setters cannot throw (for example read-only model assignment), while illegal lifecycle transitions and non-child current selection are catchable throws (ADR-0053). Reactivex Subjects raise on post-dispose use where rxjs silently no-ops (guards exist where it matters). Check ADR-0009, ADR-0037, ADR-0053, and the open items in `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` before "fixing" an apparent divergence.

## 2. Spec discipline (enforced by CI)

Two rules in `.github/workflows/spec-discipline.yml` block PRs:

1. **Any change under `spec/` requires a new ADR in `spec/ADRs/`** in the same PR. Exempt paths: `spec/README.md`, `spec/HISTORY.md`, `spec/VERSION`, `spec/ADRs/**`, `spec/fixtures/**`, `spec/proposals/**`, `spec/12-conformance.md`. A maintainer can apply the `no-adr-needed` label to bypass for typos/formatting.
2. **A new conformance ID in `spec/12-conformance.md` requires a matching test stub in every catalog-complete flavor**, in the same PR (THEME-prefixed scenario IDs are exempt — they live in example apps). This gate is a presence check. The conformance workflow's `tools/check-conformance-coverage.py` is stricter: it ignores commented-out Python, C#, and TypeScript markers. Swift and Rust intentionally use attached comment-form markers with an em dash:
   - Python: `@pytest.mark.conformance("XXX-NNN")`
   - C#: `[Trait("Conformance", "XXX-NNN")]`
   - TypeScript: `describe("XXX-NNN", ...)`
   - Swift: doc or line comments where the ID is the first token after the marker, e.g. `/// XXX-NNN — ...`, in `langs/swift/Tests/VMxTests`
   - Rust: doc comments where the ID is the first token after the marker, e.g. `/// XXX-NNN — ...`, attached to `#[test]` functions in `langs/rust/tests/conformance`

Numbered documentation headings are expected in current-facing docs, with one
intentional exception: `spec/12-conformance.md` keeps conformance IDs as heading
text (`### LIFE-001`, `### FORM-013`, …) because those IDs are the stable catalog
keys consumed by tools, tests, and review checklists.

## 3. Build / test / lint commands

`CONTRIBUTING.md` §2 is the source for each flavor's commands. It also covers the React adapter (§2.7), cross-cutting checks (§2.6), and public-API baselines (§2.8). CI runs the same commands. These notes add the setup details that the commands depend on:

- **Python environment.** Each new worktree has its own `langs/python/.venv`. In `langs/python`, set `UV_PYTHON` and run `uv sync --locked --all-extras` once before the first test (§2.2). Run `uv run python -m pytest`, never a bare `pytest`: before the sync, a bare `pytest` can run an outside `pytest` from `PATH` that imports `vmx` from another checkout.
- **One conformance ID.** `uv run python -m pytest -k LIFE_005` (Python), `dotnet test VMx.sln -c Release --filter "Conformance=LIFE-005"` (C#), `npx vitest run -t "LIFE-005"` (TypeScript).
- **Tool tests.** `uv --project langs/python run python -m pytest tools/tests/` after the sync. Run ruff on `tools/` with `--config langs/python/pyproject.toml`.
- **Swift.** `swift test` needs full Xcode (XCTest). If it reports that the Xcode license is not accepted, run `sudo xcodebuild -license accept` once. Do not chain a member access onto a dictionary lookup, as in `dict[key]?.field`; CI rejects every `]?.` (§2.4).
- **Rust packaging.** Run `cargo package` in its own `CARGO_TARGET_DIR`, as §2.5 shows. In a shared target directory it leaves a stale `vmx-rs` library that later test builds link. If that has happened, run `cargo clean -p vmx-rs` there once.
- **Pre-commit.** Run `pre-commit install` once. The hooks run ruff on Python, eslint on TypeScript, and `dotnet format --verify-no-changes` on C#. mdformat formats `spec/`, `docs/`, `langs/*/CHANGELOG.md`, and `packages/react/CHANGELOG.md`. Other hooks check whitespace, line endings, YAML, JSON, large files, and merge-conflict markers. mdformat is pinned to 0.7.x, because 1.0 is incompatible with `mdformat-gfm`.

## 4. When changing behavior

1. Update the relevant `spec/NN-*.md` chapter.
2. Add an ADR in `spec/ADRs/` describing the decision (numbered NNNN-kebab-title.md) and a row in `spec/ADRs/README.md`.
3. If the change is normative, add an ID to `spec/12-conformance.md`, an entry in the source chapter's `## Conformance` section, and a stub/marker in **all five** catalog-complete conformance suites (C#, Python, TypeScript, Swift, Rust).
4. Implement in every flavor that ships the area. Keep the public surface idiomatic per ADR-0006 and the normative concepts aligned; new flavor differences require explicit spec/ADR support. Hub `PropertyChangedMessage` names follow the flavor idiom (`"IsValid"` / `"is_valid"` / `"isValid"`); the collections `"Count"` channel is a spec-literal exception.
5. Update the public-API baseline of every flavor whose public surface changes, in the same PR (`CONTRIBUTING.md` §2.8). The C#, Python, and TypeScript checks fail on any API difference that the baseline does not record.
6. If touching `spec/fixtures/`, re-run TS `npm run sync-fixtures` and verify Python, Rust, C#, and Swift still load the file where applicable (Python/Rust tracked runtime copies, C# embedded/copy paths, and Swift package resources are configured for these exact filenames).
7. Bump `spec/VERSION` and each flavor's package version per the SemVer policy in README §6.1. Update `compatibility-matrix.md` and each flavor's `CHANGELOG.md` (bracketed Keep-a-Changelog headings). Do not copy ADR or conformance-ID counts into other files; `spec/ADRs/README.md` and the `### XXX-NNN` headings in `spec/12-conformance.md` are the only sources for them (CONTRIBUTING §3.2).
