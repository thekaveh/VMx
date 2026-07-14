# 2026-07 Maintenance Contract Ledger

Last revalidated: **2026-07-14**. This branch-independent ledger records the
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

| Area               | Authoritative pin or floor                                      | Contract                                                                                                                                                                                                                                                         | Executable evidence                                                                                                                                         |
| ------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C# runtime         | `langs/csharp/Directory.Packages.props`; project lockfiles      | `System.Reactive` and `Microsoft.Reactive.Testing` are `6.1.0`; the library targets `netstandard2.0;net8.0`; both test suites execute on `net8.0;net9.0`.                                                                                                        | `dotnet restore VMx.sln --locked-mode`; Release build/test; `dotnet format --verify-no-changes --no-restore`                                                |
| Python runtime     | `langs/python/pyproject.toml`; `langs/python/uv.lock`           | Python is `>=3.10`; `reactivex>=4.0.4` is the sole reactive runtime; the committed lock fixes the CI/dev resolution while wheel metadata retains compatible dependency ranges.                                                                                   | `uv sync --locked --all-extras`; pytest; Ruff check/format; `mypy --strict src/vmx`                                                                         |
| Python examples    | `examples/python/**/pyproject.toml`; adjacent `uv.lock` files   | The console/Tk, Notes Showcase, and Inspector executable projects each use a committed resolution; CI rejects manifest/lock drift.                                                                                                                               | `uv sync --locked --directory <project>` followed by each project's documented run, lint, type, and test gates                                              |
| Avalonia example   | Notes Showcase project and `packages.lock.json`                 | Avalonia UI/runtime packages resolve to `11.3.18`; the host consumes application/window/control, binding, dispatcher, and headless-test APIs on the Avalonia 11 line.                                                                                            | Locked restore; Release build; 152 headless tests; lock drift rejection                                                                                     |
| Textual examples   | Example `pyproject.toml` and adjacent `uv.lock` files           | Textual resolves to `8.2.8`; manifests retain the compatible `>=0.80` floor while committed locks make CI and maintenance runs reproducible.                                                                                                                     | Locked sync; Notes Showcase and Inspector lint, strict type checks, tests, and smoke runs                                                                   |
| TypeScript runtime | `langs/typescript/package-lock.json`; `package.json`            | Node is `>=20`; `rxjs` remains the sole reactive runtime; Ajv `8.20.0` validates the exported consumer-conformance schema and remains isolated from the root bundle; the package produces dual ESM/CJS output and copies shared fixtures before build/test/pack. | `npm ci`; `npm view ajv version`; fixture sync; both typechecks; lint; build; test; dist-boundary test; lockfile audit                                      |
| React example      | Notes Showcase `package.json` and `package-lock.json`           | React `18.3.1`, Vite `6.4.3`, `@vitejs/plugin-react` `4.7.0`, and Testing Library `16.3.2` are the reviewed host contract. Newer major lines require an explicit host/tooling migration.                                                                         | `npm ci`; audit; typecheck; ESLint; 227 tests; production build                                                                                             |
| Swift runtime      | `langs/swift/Package.swift`; `.github/workflows/swift.yml`      | Combine is the platform reactive primitive; package resources include all four fixtures; the declared Swift 5.9 floor is exercised with Xcode 15.0.1 on `macos-14` alongside `macos-latest`.                                                                     | Release build and parallel tests for root and nested packages on both toolchain cells                                                                       |
| Rust runtime       | `langs/rust/Cargo.toml`; `Cargo.lock`                           | `vmx-rs` is `0.22.0`, implements spec `3.20.1`, and has MSRV Rust `1.88`; runtime dependencies are the current stable `serde 1.0.228` and `thiserror 2.0.18`; the VMx-owned hot-stream facade has no `rxrust` dependency, and `serde_json` is test-only.         | `cargo search <crate> --limit 1` for both runtime crates; format; locked clippy/tests/docs/package; disposable-consumer build; empty `cargo tree -i rxrust` |
| Ratatui example    | TUI Showcase `Cargo.toml` and `Cargo.lock`                      | Ratatui `0.30.2` and crossterm `0.29.0` define the reviewed terminal frame, widget, layout, styling, event, and raw-mode contract on the Rust 1.88 floor.                                                                                                        | Locked format/clippy/build/test; five VM-layer tests; non-interactive `--smoke` run; `cargo audit --deny warnings`                                          |
| Shared contracts   | `spec/fixtures/*.json`; flavor copies; `spec/12-conformance.md` | Runtime copies remain byte-identical and all five flavors cover every library conformance ID.                                                                                                                                                                    | fixture-sync tools and `tools/check-conformance-coverage.py --require` for all five flavors                                                                 |

## 3. Tooling and documentation contracts

| Area                         | Authoritative pin or source                                                   | Contract                                                                                                                                                                    | Executable evidence                                                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Python CI bootstrap          | `.github/workflows/python.yml`                                                | `astral-sh/setup-uv` is pinned to its `v8.3.2` commit; workflow uv is exactly `0.11.28`.                                                                                    | The 3-OS / 4-version Python matrix plus example jobs                                                                              |
| Docs dependencies            | `docs/requirements.in`; hash-locked `docs/requirements.txt`                   | The Python 3.12 docs environment installs only hash-verified resolutions; pytest is `9.1.1` and pip-audit is `2.10.1`.                                                      | `pip install --require-hashes`; `python -m pip_audit --local`                                                                     |
| Three documentation surfaces | `docs/manifest.yaml`; `docs/content/**`                                       | Canonical Markdown generates in-repo navigation, the MkDocs `.io` site, and the GitHub wiki without source duplication.                                                     | `make docs-check`; strict MkDocs build; wiki dry-run/sync checks                                                                  |
| Documentation diagrams       | `docs/assets/diagrams/generate_diagrams.py`; `tools/generate-doc-diagrams.py` | Every maintained diagram has synchronized HTML/SVG/PNG output; repo-derived counts, text bounds, and raster exports are checked without mutating the worktree.              | Both generators with `--check`; `python -m scripts.docs.validate_diagrams`; diagram unit tests; original-resolution visual review |
| Rust advisory database       | `cargo-audit 0.22.2`; committed Rust lockfiles                                | RustSec vulnerabilities, unmaintained crates, unsound crates, and yanked releases fail both branch CI and the crates.io release gate.                                       | `cargo audit --file <Cargo.lock> --deny warnings` for the library and both executable examples                                    |
| GitHub Pages                 | `.github/workflows/docs.yml`                                                  | Build and pull-request jobs are read-only; only the deploy job receives `pages: write` and `id-token: write`.                                                               | `make docs-check`, artifact upload, then `actions/deploy-pages` on `main`                                                         |
| GitHub wiki                  | `.github/workflows/wiki.yml`; `scripts/docs/push_wiki.py`                     | `main` regenerates the wiki, validates diagrams, and pushes with the configured deploy key or scoped GitHub token fallback.                                                 | `push_wiki --check` dry-run before publication; `--check-published` read-only live comparison after publication                   |
| Local hygiene                | `.pre-commit-config.yaml`                                                     | Ruff covers library, tools, docs scripts, docs tests, and diagram generators; C# formatting reuses restored assets; Markdown formatting stays on canonical docs/spec paths. | `pre-commit run --all-files` after language dependencies are installed                                                            |

### 3.1 Immutable workflow action inventory

All remote actions are pinned to full commits. The upstream tag shown here was
resolved against the action repository on 2026-07-14; `dtolnay/rust-toolchain`
uses its maintained `stable` branch because that action does not publish
releases. `tools/check-workflow-pins.py` fails CI if a mutable reference appears
or any workflow action is absent from this inventory.

| Action and immutable commit                                                 | Verified upstream ref |
| --------------------------------------------------------------------------- | --------------------- |
| `NuGet/login@8d196754b4036150537f80ac539e15c2f1028841`                      | `v1.2.0`              |
| `actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0`                 | `v7.0.0`              |
| `actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d`          | `v6.0.0`              |
| `actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128`             | `v5.0.0`              |
| `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`        | `v8.0.1`              |
| `actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1`             | `v5.4.0`              |
| `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020`               | `v7.0.0`              |
| `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1`             | `v6.3.0`              |
| `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`          | `v7.0.1`              |
| `actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9`    | `v5.0.0`              |
| `astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990`               | `v8.3.2`              |
| `codecov/codecov-action@e53489f4d376d79066609109e7a95a29eb3740b1`           | `v7.0.0`              |
| `dtolnay/rust-toolchain@4be7066ada62dd38de10e7b70166bc74ed198c30`           | `stable` (2026-06-30) |
| `googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7` | `v5.0.0`              |
| `pypa/gh-action-pypi-publish@6733eb7d741f0b11ec6a39b58540dab7590f9b7d`      | `v1.14.0`             |
| `rust-lang/crates-io-auth-action@c6f97d42243bad5fab37ca0427f495c86d5b1a18`  | `v1.0.5`              |

The diagram jobs use `ubuntu-24.04` and install
`librsvg2-bin=2.58.0+dfsg-1build1` plus `pngquant=2.18.0-1build2`, the exact
Ubuntu Noble package revisions revalidated on 2026-07-14. This keeps SVG and
PNG export behavior reproducible instead of inheriting `ubuntu-latest` or
floating APT resolutions.

## 4. Release, registry, and identity contracts

| Channel     | Trigger and automation                                                                                                           | Authentication boundary                                                                                                                                                                         | Public verification                                                                                                  |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Release PRs | `release-please.yml` runs on `main`; `googleapis/release-please-action` is pinned to `45996ed1f6d02564a971a2fa1b5860e934307cf7`. | Only this workflow has `contents: write` and `pull-requests: write`; human review gates the release PR.                                                                                         | Component-prefixed tag and release manifest agree with package/changelog versions.                                   |
| NuGet       | C# tag jobs in `release.yml` package all public projects.                                                                        | `nuget-csharp` environment approval plus `id-token: write`; `NuGet/login` exchanges GitHub OIDC under the owner-created nuget.org policy.                                                       | Poll nuget.org, inspect package metadata/content, and install both `net8.0` and `netstandard2.0` in fresh consumers. |
| PyPI        | `python-v*` tag produced by release-please.                                                                                      | `pypi-python` environment approval and PyPA trusted publishing; no repository API token.                                                                                                        | Poll PyPI JSON, install the exact wheel in a fresh environment, and verify imported version/min-spec metadata.       |
| npm         | TypeScript tag job uses Node 24 and npm `11.5.1`.                                                                                | `npm-typescript` approval and OIDC trusted publishing; `NPM_TOKEN` is bootstrap-only.                                                                                                           | Poll the exact version, install under Node 20 and 22, exercise exports, and require provenance metadata.             |
| crates.io   | Rust tag job packages with the committed lock and MSRV.                                                                          | `crates-rust` approval; bootstrap token only for the first crate version, then the immutable `rust-lang/crates-io-auth-action` pin exchanges OIDC.                                              | Poll crates.io and docs.rs, then `cargo add vmx-rs@=X.Y.Z` and run fresh MSRV/stable consumers.                      |
| Swift       | Swift tags create GitHub releases; there is no central package upload.                                                           | The tag job has job-scoped `contents: write` and no protected environment; main ancestry, dual-tag equality, version parity, builds, tests, and a fresh public consumer are the trust boundary. | Resolve the exact tag through SwiftPM and build/test a fresh consumer.                                               |

### 4.1 Live GitHub control state

The following owner-controlled settings were read through the GitHub API on
2026-07-14. They are deployment prerequisites or repository-policy gaps, not
source-code secrets, and maintenance must not silently claim that they are
configured:

| Control                          | Observed state                                                                                                                                                                      | Required follow-up                                                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `nuget-csharp`                   | The environment exists with a required reviewer and tag policy, but has no `NUGET_USER` secret.                                                                                     | Add the nuget.org profile name only after its trusted-publishing policy is ready; C# publication is blocked until then.                   |
| `pypi-python`                    | The environment has a required reviewer, but `prevent_self_review` is `false` and no branch/tag deployment policy is configured.                                                    | Disable self-review and restrict deployment to the intended immutable Python release tags before the next upload.                         |
| `npm-typescript` / `crates-rust` | Both environments have required reviewers and tag policies; neither has a bootstrap token.                                                                                          | This is correct only after first publication and trusted-publisher setup; otherwise the first registry publication remains owner-blocked. |
| `gitflow` ruleset                | `main` and `develop` reject deletion/non-fast-forward updates and require PRs, but require zero approvals, zero status checks, no code-owner review, and no resolved conversations. | Select and enforce the repository's actual CI/review policy before relying on “protected branch” claims.                                  |
| Actions defaults                 | Default workflow permissions are `write`, and workflows may approve pull requests.                                                                                                  | Change the repository default to read-only and disallow workflow PR approval after confirming no workflow depends on the broader default. |

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
owner-controlled and must never be inferred, bypassed, or recorded in logs. The
live-state gaps in §4.1 remain explicit external prerequisites until the owner
changes and revalidates them.
