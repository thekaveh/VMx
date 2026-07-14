# 2026-07 Maintenance Contract Ledger

Last revalidated: **2026-07-13**. This branch-independent ledger records the
external package, tool, documentation, CI, and publication contracts consumed
by the repository. It is not a release note and does not assert that a registry
publication occurred during maintenance.

## 1. Scope and evidence policy

The ledger covers contracts that can fail independently of VMx source: reactive
runtimes, package-manager locks, compiler/runtime floors, GitHub Actions,
documentation generation, GitHub Pages/wiki publication, release automation,
OIDC exchanges, and public-registry verification. A contract is considered
verified only when its pinned source and its executable check are both named
below. Live publishing remains an owner-approved release action.

## 2. Runtime and package contracts

| Area               | Authoritative pin or floor                                      | Contract                                                                                                                                                  | Executable evidence                                                                                          |
| ------------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| C# runtime         | `langs/csharp/Directory.Packages.props`; project lockfiles      | `System.Reactive` and `Microsoft.Reactive.Testing` are `6.0.1`; the library targets `netstandard2.0;net8.0`; both test suites execute on `net8.0;net9.0`. | `dotnet restore VMx.sln --locked-mode`; Release build/test; `dotnet format --verify-no-changes --no-restore` |
| Python runtime     | `langs/python/pyproject.toml`                                   | Python is `>=3.10`; `reactivex>=4.0.4` is the sole reactive runtime; strict mypy and the project Ruff configuration are normative gates.                  | `uv sync --all-extras`; pytest; Ruff check/format; `mypy --strict src/vmx`                                   |
| TypeScript runtime | `langs/typescript/package-lock.json`; `package.json`            | Node is `>=20`; `rxjs` remains the sole reactive runtime; the package produces dual ESM/CJS output and copies shared fixtures before build/test/pack.     | `npm ci`; fixture sync; both typechecks; lint; build; test; lockfile audit                                   |
| Swift runtime      | `langs/swift/Package.swift`                                     | Combine is the platform reactive primitive; package resources include all four fixtures; XCTest requires a full Xcode installation.                       | `swift build -c release`; `swift test` on the macOS CI image                                                 |
| Rust runtime       | `langs/rust/Cargo.toml`; `Cargo.lock`                           | `vmx-rs` is `0.21.0`, MSRV is Rust `1.88`, and the VMx-owned hot-stream facade has no `rxrust` dependency. `serde_json` is test-only.                     | `cargo fmt --check`; clippy with `-D warnings`; tests; docs; package; `cargo tree -i rxrust` must be empty   |
| Shared contracts   | `spec/fixtures/*.json`; flavor copies; `spec/12-conformance.md` | Runtime copies remain byte-identical and all five flavors cover every library conformance ID.                                                             | fixture-sync tools and `tools/check-conformance-coverage.py --require` for all five flavors                  |

## 3. Tooling and documentation contracts

| Area                         | Authoritative pin or source                                                   | Contract                                                                                                                                                                    | Executable evidence                                                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Python CI bootstrap          | `.github/workflows/python.yml`                                                | `astral-sh/setup-uv` is pinned to commit `caf0cab7a618c569241d31dcd442f54681755d39`; workflow uv is `0.11.19`.                                                              | The 3-OS / 4-version Python matrix plus example jobs                                                                              |
| Docs dependencies            | `docs/requirements.in`; hash-locked `docs/requirements.txt`                   | The Python 3.12 docs environment installs only hash-verified resolutions; pytest is `9.1.1` and pip-audit is `2.10.1`.                                                      | `pip install --require-hashes`; `python -m pip_audit --local`                                                                     |
| Three documentation surfaces | `docs/manifest.yaml`; `docs/content/**`                                       | Canonical Markdown generates in-repo navigation, the MkDocs `.io` site, and the GitHub wiki without source duplication.                                                     | `make docs-check`; strict MkDocs build; wiki dry-run/sync checks                                                                  |
| Documentation diagrams       | `docs/assets/diagrams/generate_diagrams.py`; `tools/generate-doc-diagrams.py` | Every maintained diagram has synchronized HTML/SVG/PNG output; repo-derived counts, text bounds, and raster exports are checked without mutating the worktree.              | Both generators with `--check`; `python -m scripts.docs.validate_diagrams`; diagram unit tests; original-resolution visual review |
| GitHub Pages                 | `.github/workflows/docs.yml`                                                  | Build and pull-request jobs are read-only; only the deploy job receives `pages: write` and `id-token: write`.                                                               | `make docs-check`, artifact upload, then `actions/deploy-pages` on `main`                                                         |
| GitHub wiki                  | `.github/workflows/wiki.yml`; `scripts/docs/push_wiki.py`                     | `main` regenerates the wiki, validates diagrams, and pushes with the configured deploy key or scoped GitHub token fallback.                                                 | generated wiki comparison and `push_wiki --check` before publication                                                              |
| Local hygiene                | `.pre-commit-config.yaml`                                                     | Ruff covers library, tools, docs scripts, docs tests, and diagram generators; C# formatting reuses restored assets; Markdown formatting stays on canonical docs/spec paths. | `pre-commit run --all-files` after language dependencies are installed                                                            |

## 4. Release, registry, and identity contracts

| Channel     | Trigger and automation                                                                                                           | Authentication boundary                                                                                                                            | Public verification                                                                                                  |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Release PRs | `release-please.yml` runs on `main`; `googleapis/release-please-action` is pinned to `5c625bfb5d1ff62eadeeb3772007f7f66fdcf071`. | Only this workflow has `contents: write` and `pull-requests: write`; human review gates the release PR.                                            | Component-prefixed tag and release manifest agree with package/changelog versions.                                   |
| NuGet       | C# tag jobs in `release.yml` package all public projects.                                                                        | `nuget-csharp` environment approval plus `id-token: write`; `NuGet/login` exchanges GitHub OIDC under the owner-created nuget.org policy.          | Poll nuget.org, inspect package metadata/content, and install both `net8.0` and `netstandard2.0` in fresh consumers. |
| PyPI        | `python-v*` tag produced by release-please.                                                                                      | `pypi-python` environment approval and PyPA trusted publishing; no repository API token.                                                           | Poll PyPI JSON, install the exact wheel in a fresh environment, and verify imported version/min-spec metadata.       |
| npm         | TypeScript tag job uses Node 24 and npm `11.5.1`.                                                                                | `npm-typescript` approval and OIDC trusted publishing; `NPM_TOKEN` is bootstrap-only.                                                              | Poll the exact version, install under Node 20 and 22, exercise exports, and require provenance metadata.             |
| crates.io   | Rust tag job packages with the committed lock and MSRV.                                                                          | `crates-rust` approval; bootstrap token only for the first crate version, then the immutable `rust-lang/crates-io-auth-action` pin exchanges OIDC. | Poll crates.io and docs.rs, then `cargo add vmx-rs@=X.Y.Z` and run fresh MSRV/stable consumers.                      |
| Swift       | Swift tags create GitHub releases; there is no central package upload.                                                           | GitHub release permissions and the release environment remain the trust boundary.                                                                  | Resolve the exact tag through SwiftPM and build/test a fresh consumer.                                               |

## 5. Revalidation checklist

1. Resolve only through committed locks or hash files and fail on drift.
1. Run language-native lint, format, build, test, package, and audit gates.
1. Run fixture synchronization and five-flavor conformance coverage.
1. Run both diagram generators in `--check` mode and the full three-surface docs gate.
1. Verify workflow action references, job-scoped permissions, environments, and OIDC subject names.
1. For a release, require the public artifact and a fresh exact-version consumer before declaring success.

## 6. Known environmental boundaries

Local Swift tests are unavailable when only Command Line Tools are selected;
macOS CI with full Xcode is authoritative. Registry credentials, environment
approvals, trusted-publisher policies, and first-publication bootstrap steps are
owner-controlled and must never be inferred, bypassed, or recorded in logs.
