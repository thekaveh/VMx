# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 1. Architecture

VMx is **one language-neutral specification with five idiomatic flavors**. All five are catalog-complete for the 396 library conformance IDs. C#, Python, TypeScript, and Swift are member-aligned; Rust's remaining public-surface and behavior convergence gaps are tracked in `docs/maintenance/2026-07-16-rust-capability-parity.md`. Naming remains idiomatic (PascalCase C#, snake_case Python and Rust methods, camelCase TypeScript and Swift — codified in `spec/ADRs/0006-idiomatic-api-per-language.md`).

- **`spec/` is the source of truth.** 24 numbered markdown chapters (`00-overview.md` … `23-async-resource-vm.md`), 124 ADRs, four JSON fixtures, supporting schemas, current version in `spec/VERSION` (3.22.0). Behavior changes start here.
- **`spec/fixtures/*.json` are consumed by all flavors** for lifecycle, message-ordering, command-truthtable, and derived-property validation. Python tracks `lifecycle-transitions.json` under `langs/python/src/vmx/lifecycle/_data/` for runtime loading, and `tools/check-python-fixture-sync.py` keeps it byte-identical to the spec fixture; Rust tracks the same runtime fixture under `langs/rust/src/fixtures/` so the published crate is self-contained, and `tools/check-rust-fixture-sync.py` keeps that copy byte-identical. The other fixtures are conformance-test inputs. TypeScript copies all fixtures via `npm run sync-fixtures` (auto-run by `prebuild`, `pretest`, and `prepack`). C# embeds `lifecycle-transitions.json` for runtime and copies all fixtures into conformance test output. Swift ships all four JSON resources under `langs/swift/Sources/VMx/Resources`, including `LifecycleTransitionTable.swift` loading `lifecycle-transitions.json` from `Bundle.module`. When editing a fixture, ensure every flavor still loads the relevant runtime/test resource.
- **`spec/12-conformance.md` enumerates 401 normative test IDs** — 396 library IDs (`LIFE-001`, `HUB-013`, `CVM-010`, `SUBV-004`, `AGCH-010`, `SRCH-007`, `ARES-011`, `DISP-014`, `FORM-030`, `COL-064`, `BLD-006`, `GRP-011`, `HIER-030`, `NOTIF-017`, `COMP-041`, `DISC-006`, …) plus 5 `THEME-00x` scenario IDs that live in the flagship example apps. C#, Python, TypeScript, Swift, and Rust each implement all 396 library IDs under their conformance test trees. `tools/check-conformance-coverage.py` enforces 100% catalog coverage for all five flavors in CI; coverage alone does not prove member-level parity.
- **Each flavor versions independently** but a spec major bump triggers a major bump in every active flavor. Each package declares the spec version it implements: `MinSpecVersion` (C#), `__min_spec_version__` (Python), `__minSpecVersion__` (TypeScript), `VMxVersion.minSpecVersion` (Swift), `MIN_SPEC_VERSION` (Rust). Compatibility is recorded in `compatibility-matrix.md`; release-please updates the current Python cell, while spec and other flavor changes remain explicit edits.
- **Per-flavor source layout mirrors the spec chapters** — `aggregates/`, `builders/`, `commands/`, `components/`, `composites/`, `forwarding/`, `groups/`, `lifecycle/`, `messages/`, `services/`, `tree/`, `collections/`, `capabilities/`, `properties/` (DerivedProperty), `notifications` (opt-in package/sub-path where applicable), `localization/`, `hierarchical/`, `dialogs/`, `forms/`, and `state/` (DiscriminatorVM). When adding a primitive, add it to the same-named area in every supported flavor that ships the area.
- **Reactive primitive per flavor**: C# uses `System.Reactive`, Python uses `reactivex`, TypeScript uses `rxjs`, Swift uses `Combine` (macOS-only — no Linux CI for Swift), and Rust uses VMx-owned hot-stream facades with no third-party reactive runtime per ADR-0103. Don't introduce additional reactive libraries.
- **Known cross-flavor divergences are documented**, not accidental: Swift still traps where Swift setters cannot throw (for example read-only model assignment), while illegal lifecycle transitions and non-child current selection are catchable throws after the v3 convergence. Reactivex Subjects raise on post-dispose use where rxjs silently no-ops (guards exist where it matters). Check ADR-0009, ADR-0037, and ADR-0053 before "fixing" an apparent divergence.

## 2. Spec discipline (enforced by CI)

Two rules in `.github/workflows/spec-discipline.yml` block PRs:

1. **Any change under `spec/` requires a new ADR in `spec/ADRs/`** in the same PR. Exempt paths: `spec/README.md`, `spec/VERSION`, `spec/ADRs/**`, `spec/fixtures/**`, `spec/proposals/**`, `spec/12-conformance.md`. A maintainer can apply the `no-adr-needed` label to bypass for typos/formatting.
2. **A new conformance ID in `spec/12-conformance.md` requires a matching test stub in every catalog-complete flavor**, in the same PR (THEME-prefixed scenario IDs are exempt — they live in example apps). Stub patterns the check recognizes (regex-based — a commented-out stub also matches, so don't rely on comments to park IDs):
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

### 3.1 Python (`langs/python`)
```bash
cd langs/python
uv sync --all-extras
uv run pytest                              # full suite
uv run pytest tests/conformance            # conformance only
uv run pytest -k LIFE_005                  # a single conformance ID
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx               # must be strict-clean
```

### 3.2 C# (`langs/csharp`)
```bash
cd langs/csharp
dotnet restore VMx.sln --locked-mode
dotnet build
dotnet test                                # both VMx.Tests + VMx.Conformance.Tests
dotnet test --filter "Conformance=LIFE-005"
dotnet format --verify-no-changes
```
Central package versions live in `Directory.Packages.props`; common project settings in `Directory.Build.props` (`TreatWarningsAsErrors=true`, `Nullable=enable`).

### 3.3 TypeScript (`langs/typescript`)
```bash
cd langs/typescript
npm ci
npm run sync-fixtures   # copies spec/fixtures/*.json → src/fixtures/ (required after spec fixture edits)
npm run typecheck
npm run typecheck:tests
npm run lint
npm run build           # tsup, dual ESM + CJS
npm test                # vitest run
npx vitest run -t "LIFE-005"   # single conformance ID
```
Published VMx supports Node ≥ 20. Repository tests require Node 20.19+, 22.13+,
or 24+ (jsdom 29 development-tool floor).

### 3.4 Swift (`langs/swift`)
```bash
cd langs/swift
swift build             # compiles on CommandLineTools
swift test              # requires full Xcode (XCTest); CI runs it on macos-latest
```
If `swift test` reports the Xcode license is not accepted, run `sudo xcodebuild -license accept` once.

### 3.5 Rust (`langs/rust`)
```bash
cd langs/rust
cargo fmt --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --all-features --no-deps
cargo package --locked
```

### 3.6 Conformance coverage tool
```bash
# Report-only across flavors
python3 tools/check-conformance-coverage.py

# CI mode (matches the conformance workflow)
uv --project langs/python run python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript --require swift --require rust

# The tool's own unit tests
uv --project langs/python run pytest tools/tests/
```
Running ruff on `tools/` requires the project config: `--config langs/python/pyproject.toml`.

### 3.7 Pre-commit
`pre-commit install` once. Hooks: ruff (Python only), mdformat (spec/ and docs/), `dotnet format --verify-no-changes` (C# only), eslint (TypeScript only), whitespace/EOL hygiene. mdformat is pinned to 0.7.x (1.0 is incompatible with `mdformat-gfm`).

## 4. When changing behavior

1. Update the relevant `spec/NN-*.md` chapter.
2. Add an ADR in `spec/ADRs/` describing the decision (numbered NNNN-kebab-title.md) and a row in `spec/ADRs/README.md`.
3. If the change is normative, add an ID to `spec/12-conformance.md`, an entry in the source chapter's `## Conformance` section, and a stub/marker in **all five** catalog-complete conformance suites (C#, Python, TypeScript, Swift, Rust).
4. Implement in every flavor that ships the area. Keep the public surface idiomatic per ADR-0006 and the normative concepts aligned; do not treat the documented Rust backlog as license for new divergence. Hub `PropertyChangedMessage` names follow the flavor idiom (`"IsValid"` / `"is_valid"` / `"isValid"`); the collections `"Count"` channel is a spec-literal exception.
5. If touching `spec/fixtures/`, re-run TS `npm run sync-fixtures` and verify Python, Rust, C#, and Swift still load the file where applicable (Python/Rust tracked runtime copies, C# embedded/copy paths, and Swift package resources are configured for these exact filenames).
6. Bump `spec/VERSION` and each flavor's package version per the SemVer policy in README §6.1. Update `compatibility-matrix.md`, each flavor's `CHANGELOG.md` (bracketed Keep-a-Changelog headings), and the count claims in README/spec/README/flavor READMEs.
