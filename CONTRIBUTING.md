# Contributing to VMx

Thanks for your interest in contributing!

## 1. Workflow

1. Open an issue describing the change before opening a PR for anything non-trivial.
2. Branch from the default integration branch, `develop`. Use a descriptive
   branch name (`feat/...`, `fix/...`, `docs/...`).
3. Run the relevant test suite locally before pushing.
4. Open a PR to `develop`. Direct pushes are blocked. The protected-branch
   ruleset requires the always-present conformance, five-flavor, docs, examples,
   security, and spec-discipline aggregate checks to pass against the latest
   target branch. Obtain maintainer review when another reviewer is available;
   the repository currently has one direct collaborator, so the ruleset does
   not impose an impossible self-approval requirement.
5. Maintainers promote `develop` to protected `main` through a separate PR.

## 2. Per-language setup

### 2.1 C#

```bash
cd langs/csharp
dotnet restore VMx.sln --locked-mode   # --locked-mode matches CI; fails fast on lockfile drift
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build
dotnet format VMx.sln --verify-no-changes
```

### 2.2 Python

```bash
cd langs/python
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

### 2.3 TypeScript

```bash
cd langs/typescript
npm ci
npm run sync-fixtures   # copy spec/fixtures/*.json → src/fixtures/
npm run typecheck
npm run typecheck:tests # type-check tests/ separately; CI runs this too
npm run lint
npm run build
npm test
```

### 2.4 Swift

```bash
cd langs/swift
swift build -c release
swift test --parallel
```

Swift requires the toolchain shipped with a current Xcode (5.9+) and a
macOS / iOS / tvOS / watchOS host — the flavor depends on Combine, which
is not available on Linux. See `langs/swift/README.md` §5 for the full
conformance matrix; the current source line is at full library parity.

### 2.5 Rust

```bash
cd langs/rust
cargo fmt --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --all-features --no-deps
cargo package --locked
```

Rust's minimum supported toolchain is 1.88. Keep the committed library and
example lockfiles current.

### 2.6 Cross-cutting checks (conformance + example-app contracts)

Two CI-only workflows enforce repo-wide invariants. To run the same
checks locally before pushing:

```bash
# Cross-language library conformance coverage (all five flavors).
# Mirrors .github/workflows/conformance.yml. THEME-001..005 live in
# example apps, not language libraries, so they're intentionally excluded.
uv run --project langs/python python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript --require swift \
    --require rust

# Pure-VM contract + flagship example-app parity
# (Avalonia / Textual / React / SwiftUI).
# Mirrors .github/workflows/examples-contract-checks.yml.
python3 tools/check-axaml-codebehind.py
python3 tools/check-textual-views.py
python3 tools/check-layer-imports.py
python3 tools/check-showcase-parity.py
```

## 3. Spec-driven changes

Behavior changes start in `spec/`. The rules are:

- A spec change requires a matching ADR in `spec/ADRs/`. This is enforced by the
  `spec-discipline` CI check.
- Files exempt from the ADR requirement: `spec/README.md`, `spec/VERSION`,
  `spec/ADRs/**`, `spec/fixtures/**`, `spec/12-conformance.md` (adding catalog
  IDs is governed by the conformance-stub rule below, not by ADRs), and
  `spec/proposals/**` (historical planning artifacts; landed proposals are
  already covered by the ADR they introduced).
- A new conformance test ID in `spec/12-conformance.md` requires a matching test stub
  in **every** active language flavor in the same PR. The CI check looks for
  `@pytest.mark.conformance("XXX-NNN")` (Python), `[Trait("Conformance", "XXX-NNN")]`
  (C#), `describe("XXX-NNN", ...)` (TypeScript), Swift doc / line comments
  where the ID is the first token after the marker (for example
  `/// XXX-NNN - ...`) in `langs/swift/Tests/VMxTests`, and equivalent leading
  doc comments on Rust `#[test]` functions under `langs/rust/tests/conformance`.

### 3.1 Bypass

If a spec change genuinely does not warrant an ADR (e.g., a typo fix or pure
formatting change), a maintainer may add the `no-adr-needed` PR label to bypass the
ADR check. Use sparingly; the label is intended for changes with zero semantic effect.

See the ADRs in `spec/ADRs/` for the rationale behind each architectural rule.

## 4. Releases and tagging

Each flavor versions and releases independently. Most operational tags use
`<lang>-vX.Y.Z`, where `<lang>` is `csharp`, `python`, `typescript`, `swift`, or
`rust`. C# keeps that form for the core `VMx` package and uses package-specific
`csharp-notifications-vX.Y.Z` and `csharp-dependency-injection-vX.Y.Z` tags for
its independently versioned companions. A spec tag uses `spec-vX.Y.Z`. Swift
additionally requires a semantic `vX.Y.Z` tag for SwiftPM, paired with its
`swift-vX.Y.Z` operational tag.

### 4.1 Why all three families

- A flavor/package tag starts only its matching release jobs and artifact.
- Package versions do not need to match one another or the spec's minor/patch
  version; each package declares the minimum spec version it implements.
- A spec major bump requires a major bump in every active flavor.
- Tags and registry versions are immutable after publication.

### 4.2 Cutting a release

Start from a clean, verified `origin/main`, prove the intended tag and public
version are unused, then follow the flavor-specific runbook:

- [`langs/csharp/RELEASING.md`](langs/csharp/RELEASING.md)
- [`langs/python/RELEASING.md`](langs/python/RELEASING.md)
- [`langs/typescript/RELEASING.md`](langs/typescript/RELEASING.md)
- [`langs/swift/RELEASING.md`](langs/swift/RELEASING.md)
- [`langs/rust/RELEASING.md`](langs/rust/RELEASING.md)

Registry-backed releases require their protected GitHub environment, trusted
publisher/OIDC policy, public artifact verification, and a fresh exact-version
consumer. Never create or move release tags from `develop`.

### 4.3 Source-version invariant

`main` may contain an in-development source version before publication. The
compatibility matrix must distinguish source status from public package status,
and release automation must verify exact tag/package agreement before upload.

## 5. Code of conduct

This project follows the Contributor Covenant v2.1 — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
