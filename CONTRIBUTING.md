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
   target branch. Obtain maintainer review when another reviewer is available.
   The repository has one direct collaborator, so the ruleset does not require
   self-approval.
5. Maintainers promote `develop` to protected `main` through a separate PR.

### 1.1 Branch sync policy

`develop` and `main` stay in sync by tree, not by history. The
`develop-gitflow` ruleset permits squash merges only, and the `main-gitflow`
ruleset permits merge commits only. No permitted PR can bring a `main` merge
commit into `develop`, so `develop` history does not contain the `main` merge
commits. `git rev-list --count origin/develop..origin/main` is therefore
never 0, and it grows by one with each promotion.

- **Promotion.** Each promotion PR from `develop` to `main` merges with a merge
  commit. GitHub reports every promotion PR as `BEHIND` `main`. This state is
  expected and does not show that the promotion head is out of date. After the
  merge, check that `main` has the promotion head's tree; the command exits 0:

  ```bash
  git fetch origin
  git diff --quiet <promotion head> <main merge commit>
  ```

- **Back-sync.** A change that reaches `main` by another route, such as a
  merged release-please release PR, does not reach `develop` by itself. Before
  the next promotion, open a squash PR to `develop` from a branch cut at that
  `main` commit. After it merges, `git diff --quiet origin/main origin/develop`
  exits 0 when no other change has landed on `develop` since.

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
export UV_PYTHON=3.12
uv python install "$UV_PYTHON"
uv sync --locked --all-extras
uv run python ../../tools/check-python-interpreter.py --venv .venv
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```

Choose any supported Python 3.10–3.14 version with `UV_PYTHON`; in PowerShell,
use `$env:UV_PYTHON = "3.12"`. Installing an interpreter alone does not select
it for a compatible existing uv environment. Keep the selector set for sync,
run, build, and tool commands.

CI selects each matrix version the same way and checks the interpreter
identity before every lint, typing, and test step. The Ubuntu 3.10 cell first
seeds a 3.14 environment and checks that a selected sync repairs it.

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

Vitest global setup builds the package before test workers start, also for
direct `npx vitest`, watch, and coverage runs. Rerun manually after editing
spec inputs outside Vitest's import graph, and do not start a separate build
while tests run.

### 2.4 Swift

```bash
cd langs/swift
swift build -c release
swift test --parallel
```

Swift requires the toolchain of a current Xcode (CI uses Swift 6.0 and later;
the manifest declares tools version 5.9) and a macOS / iOS / tvOS / watchOS
host — the flavor depends on Combine, which
is not available on Linux. See `langs/swift/README.md` §5 for the conformance
summary and the Swift-specific divergences.

Do not chain a member access onto a dictionary lookup, as in
`dict[key]?.field`. Apple Swift 6.4 (swiftlang-6.4.0.34.1) at `-Onone` can
return a non-nil value from that expression when the key is missing; `-O`
builds return `nil`. `swift build` and `swift test` use the debug
configuration, which compiles at `-Onone`. Bind the lookup first, with
`if let value = dict[key] { ... }` or
`guard let value = dict[key] else { ... }`, and then read the field. The
`swift` workflow runs `python3 tools/check-swift-subscript-chains.py`, which
fails on any `]?.` in the root `Package.swift` and in the Swift files under
`langs/swift`, `examples/swift` and `starters/swift-package` (#1462). An
upstream Swift report is not filed yet.

### 2.5 Rust

```bash
cd langs/rust
cargo fmt --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-features
cargo test --locked                        # default features: test seams compiled out
RUSTDOCFLAGS="-D warnings" cargo doc --locked --all-features --no-deps
cargo package --locked
python3 ../../tools/check-rust-package.py  # crate holds exactly the tracked files
```

Rust's minimum supported toolchain is 1.88. The `rust` workflow runs every
gate in this block on 1.88.0. On stable it runs the format check, the
all-feature Clippy, test and documentation gates, and the package check. Run
Clippy on both toolchains before you push. Keep the committed library and
example lockfiles current.

### 2.6 Cross-cutting checks (conformance + example-app contracts)

These checks mirror `conformance.yml`, `examples-contract-checks.yml`, and
each flavor workflow. Run them locally before pushing:

```bash
# Cross-language library conformance coverage (all five flavors).
# Mirrors .github/workflows/conformance.yml. THEME-001..005 live in
# example apps, not language libraries, so they're intentionally excluded.
uv run --project langs/python python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript --require swift \
    --require rust

# Executed conformance evidence for one flavor, from its runner's own report.
# Each flavor workflow runs this after its tests; for example, Python:
(cd langs/python && uv run pytest --junitxml=conformance-results.xml \
    -o junit_family=xunit1)
python3 tools/check-conformance-execution.py --flavor python \
    --report langs/python/conformance-results.xml

# Pure-VM contract + flagship example-app parity
# (Avalonia / Textual / React / SwiftUI).
# Mirrors .github/workflows/examples-contract-checks.yml.
python3 tools/check-axaml-codebehind.py
python3 tools/check-textual-views.py
python3 tools/check-layer-imports.py
python3 tools/check-showcase-parity.py
```

### 2.7 React adapter (`packages/react`)

The adapter resolves `@thekaveh/vmx` from `langs/typescript`, so build the core
first:

```bash
npm ci --prefix langs/typescript
npm run build --prefix langs/typescript
cd packages/react
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

### 2.8 Public API baselines

Each flavor's CI compares the public API of its packages with a recorded
baseline (#1365). The C#, Python and TypeScript checks fail on any
difference from a tracked API listing, an added member included. The Rust and
Swift checks build a recorded baseline revision and fail on a break.

| Flavor | Baseline | CI check | Intended change |
|---|---|---|---|
| C# | `PublicAPI.Shipped.txt` and `PublicAPI.Unshipped.txt` next to each library project; `langs/csharp/src/VMx/PublicAPI/net8.0/` lists the members that only `net8.0` declares | `dotnet build` (PublicApiAnalyzers: RS0016 for a member that the files do not list, RS0017 for a listed member that is gone) | Add new members to `PublicAPI.Unshipped.txt` with the RS0016 code fix, or with `dotnet format analyzers VMx.sln --diagnostics RS0016 --severity warn` (run it again until the count stops changing). Delete or edit the line of a removed or changed member. |
| Python | `langs/python/api/vmx.api.txt` | `tools/check-python-api.py` on Python 3.12 | In `langs/python`: `uv run --python 3.12 python ../../tools/check-python-api.py --update` |
| TypeScript | `langs/typescript/api/vmx.api.txt` | `tools/check-typescript-api.py` after `npm run build` | In `langs/typescript`: `npm run build && python3 ../../tools/check-typescript-api.py --update` |
| Rust | `langs/rust/api/baseline-revision` | `cargo semver-checks` 0.51.0 on Rust 1.99.1 | Bump the `Cargo.toml` version as SemVer requires; the tool then accepts the break. |
| Swift | `langs/swift/api/baseline-revision` and `langs/swift/api/breakage-allowlist.txt` | `swift package diagnose-api-breaking-changes` on the root package's `VMx` product | Add each reported `API breakage: ...` line to the allowlist. |

Commit the updated baseline in the same PR as the API change, so that the
review shows it. A removed or changed public member is a breaking change: it
needs a major version bump, or a minor bump while the version is 0.x (as for
`vmx-rs`). An added member needs a minor bump (README §6.1). After a Rust or
Swift release, set that flavor's `baseline-revision` to the release commit and
empty the Swift allowlist.

The local commands match CI:

```bash
(cd langs/csharp && dotnet build VMx.sln -c Release)
(cd langs/python && uv run --python 3.12 python ../../tools/check-python-api.py)
(cd langs/typescript && npm run build && python3 ../../tools/check-typescript-api.py)
cargo install cargo-semver-checks --version 0.51.0 --locked
cargo semver-checks check-release --manifest-path langs/rust/Cargo.toml \
    --baseline-rev "$(tr -d '[:space:]' < langs/rust/api/baseline-revision)" \
    --default-features
swift package diagnose-api-breaking-changes \
    "$(tr -d '[:space:]' < langs/swift/api/baseline-revision)" --products VMx \
    --breakage-allowlist-path langs/swift/api/breakage-allowlist.txt
```

## 3. Spec-driven changes

Behavior changes start in `spec/`. The rules are:

- A spec change requires a matching ADR in `spec/ADRs/`. This is enforced by the
  `spec-discipline` CI check.
- Files exempt from the ADR requirement: `spec/README.md`, `spec/HISTORY.md`,
  `spec/VERSION`, `spec/ADRs/**`, `spec/fixtures/**`, `spec/12-conformance.md` (adding catalog
  IDs is governed by the conformance-stub rule below, not by ADRs), and
  `spec/proposals/**` (historical planning artifacts; landed proposals are
  already covered by the ADR they introduced).
- A new conformance test ID in `spec/12-conformance.md` requires a matching test stub
  in **every** active language flavor in the same PR. The CI check looks for
  `@pytest.mark.conformance("XXX-NNN")` (Python), `[Trait("Conformance", "XXX-NNN")]`
  (C#), `describe("XXX-NNN", ...)` (TypeScript), Swift doc / line comments
  where the ID is the first token after the marker (for example
  `/// XXX-NNN — ...`, with an em dash) in `langs/swift/Tests/VMxTests`, and equivalent leading
  doc comments, also with an em dash, on Rust `#[test]` functions under
  `langs/rust/tests/conformance`.

### 3.1 Bypass

If a spec change genuinely does not warrant an ADR (e.g., a typo fix or pure
formatting change), a maintainer may add the `no-adr-needed` PR label to bypass the
ADR check. Use sparingly; the label is intended for changes with zero semantic effect.

See the ADRs in `spec/ADRs/` for the rationale behind each architectural rule.

## 4. Releases and tagging

Each flavor versions and releases independently. Most operational tags use
`<lang>-vX.Y.Z`, where `<lang>` is `csharp`, `python`, `typescript`, `swift`,
`rust`, or `react` (the React adapter). C# keeps that form for the core `VMx`
package and uses package-specific `csharp-notifications-vX.Y.Z` and
`csharp-dependency-injection-vX.Y.Z` tags for its independently versioned
companions. A spec tag uses `spec-vX.Y.Z`. Swift
additionally requires a semantic `vX.Y.Z` tag for SwiftPM, paired with its
`swift-vX.Y.Z` operational tag.

### 4.1 Versioning rules

Package versions do not need to match one another or the spec's minor/patch
version. Spec compatibility, tag selection, and immutability rules are in
[Release invariants](#43-release-invariants).

### 4.2 Cutting a release

Start from a clean, verified `origin/main`, prove the intended tag and public
version are unused, then follow the flavor-specific runbook:

- [`langs/csharp/RELEASING.md`](langs/csharp/RELEASING.md)
- [`langs/python/RELEASING.md`](langs/python/RELEASING.md)
- [`langs/typescript/RELEASING.md`](langs/typescript/RELEASING.md)
- [`packages/react/RELEASING.md`](packages/react/RELEASING.md) (React adapter)
- [`langs/swift/RELEASING.md`](langs/swift/RELEASING.md)
- [`langs/rust/RELEASING.md`](langs/rust/RELEASING.md)

Every runbook applies the [release invariants](#43-release-invariants).
Registry-backed releases also require public artifact verification and a fresh
exact-version consumer.

### 4.3 Release invariants

These rules apply to every flavor runbook. Each runbook adds only its
flavor-specific steps.

**Protected environment.** Each registry-backed channel publishes through one
protected GitHub environment. Swift has no registry and no environment.
Configure each environment as follows:

- Restrict deployments to the flavor's tag pattern.
- Require a maintainer reviewer.
- Disable administrator bypass. With bypass allowed, an administrator's tag
  push publishes without waiting for approval.
- Leave "Prevent self-review" off while one maintainer holds the reviewer role.
  Otherwise that maintainer cannot approve their own release. Revisit this rule
  when a second maintainer joins.
- Keep any credential on the environment, never as a repository-wide secret.

**Trusted publisher.** Registry channels authenticate through GitHub OIDC; the
publish job has `id-token: write`. A registry that requires an existing package
needs a one-time bootstrap credential first; the flavor runbook describes it.
Register the trusted publisher with these exact fields:

| Field             | Value                              |
| ----------------- | ---------------------------------- |
| Owner             | `thekaveh`                         |
| Repository        | `VMx`                              |
| Workflow filename | `release.yml` (filename only)      |
| Environment       | the flavor's protected environment |

Do not add a long-lived registry token or bypass the environment.

**Publish job isolation.** In a job with `id-token: write`, every step can
request an OIDC token that the trusted publisher accepts. So only the publish
job has that permission and the protected environment. Earlier jobs without it
install dependencies, build, lint, test, audit, run the consumer smoke checks,
and upload the exact artifact: the NuGet packages, the Python `dist/` files, or
the npm tarball. The publish job downloads that artifact and publishes it. Apart
from the pinned npm CLI, it installs, builds, and tests nothing. Rust is the one
exception: `cargo publish` cannot publish a prepared `.crate`, so its
verification build still compiles the crate's dependencies in the publish job.
The `rust-test` job runs the packaged-consumer check without `id-token: write`.
`tools/tests/test_ci_workflow_contracts.py` enforces this split. It does not
protect against a build step that changes the artifact before the upload.

**Tags.** Create every manual release tag as an annotated tag on the verified
`origin/main` commit, then push it:

```bash
git tag -a "<tag>" -m "<package> <version>" origin/main
git push origin "<tag>"
```

This rule includes Python: release-please creates no tags or GitHub Releases
(`skip-github-release: true`). Older Python tags such as `python-v3.23.1` are
lightweight, because release-please created them. The release workflow still
accepts both kinds. Never create a release tag from `develop`.

**Immutability.** Tags and registry versions are immutable, even when a release
fails before upload. Never move, delete, or recreate a release tag. Fix the
cause on `main` through the normal PR flow, bump the package to a new patch
version, and release it with a new tag.

**Spec compatibility.** Each package declares the minimum spec version it
implements. A spec major bump requires a major bump in every active flavor
(`README.md` §6.1).

**Tag prefixes.** Every operational tag prefix (`csharp-*`, `python-v`,
`typescript-v`, `react-v`, `rust-v`, `swift-v`) selects only its own release
jobs. Spec tags and Swift semantic tags trigger no release jobs. `release.yml`
filters jobs by prefix, so one flavor's tag never publishes another package.

**Source version.** `main` may contain an in-development source version before
publication. The compatibility matrix must distinguish source status from
public package status. Release automation verifies exact tag/package agreement
before upload.

**Publication claims.** Publication claims never precede public evidence. After
the public artifact and a fresh consumer verify, update the repository docs and
regenerate the documentation site and wiki through `develop` and `main` PRs.

### 4.4 Validate Python release tests without publishing

Run the release workflow on the default branch, `develop`:

```bash
gh workflow run release.yml --ref develop
```

This no-input dispatch runs only the five-version Ubuntu `python-test` matrix.
Every other release job requires a tag push, even when a dispatch targets an
existing release tag. Validation cannot publish packages or create releases,
and it does not exercise the Python build or protected publish jobs. Normal Python
CI separately checks the wheel and extracted sdist. Real tag pushes retain
their `origin/main` ancestry check and all publication protections.

To verify warm-cache behavior, rerun the successful workflow at the same
revision and inspect the 3.10 cell for `cache-hit=true`, both managed Python
versions, the seeded 3.14 identity, and the repaired 3.10 identity. A cache miss
does not establish warm-cache coverage. Record the run URL and exact revision.

## 5. Code of conduct

This project follows the Contributor Covenant v2.1 — see [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
