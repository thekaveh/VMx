# 2026-07 Maintenance Contract Ledger

Last revalidated: **2026-07-18**. This branch-independent ledger records the
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

| Area               | Authoritative pin or floor                                      | Contract                                                                                                                                                                                                                                                                                                                                            | Executable evidence                                                                                                                                                |
| ------------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| C# runtime         | `langs/csharp/Directory.Packages.props`; project lockfiles      | `System.Reactive` and `Microsoft.Reactive.Testing` are `7.0.0`, with `System.Collections.Immutable` `10.0.10`; the library targets `netstandard2.0;net8.0`; both test suites execute on `net8.0;net9.0;net10.0`.                                                                                                                                    | `dotnet restore VMx.sln --locked-mode`; Release build/test; `dotnet format --verify-no-changes --no-restore`                                                       |
| Python runtime     | `langs/python/pyproject.toml`; `langs/python/uv.lock`           | Python is `>=3.10`; `reactivex>=4.0.4` is the sole reactive runtime; the committed lock fixes the CI/dev resolution while wheel metadata retains compatible dependency ranges.                                                                                                                                                                      | `uv sync --locked --all-extras`; pytest; Ruff check/format; `mypy --strict src/vmx`                                                                                |
| Python examples    | `examples/python/**/pyproject.toml`; adjacent `uv.lock` files   | The console/Tk, Notes Showcase, and Inspector executable projects each use a committed resolution; CI rejects manifest/lock drift.                                                                                                                                                                                                                  | `uv sync --locked --directory <project>` followed by each project's documented run, lint, type, and test gates                                                     |
| Avalonia example   | Notes Showcase project and `packages.lock.json`                 | Avalonia UI/runtime packages resolve to `11.3.18`; the host consumes application/window/control, binding, dispatcher, and headless-test APIs on the Avalonia 11 line.                                                                                                                                                                               | Locked restore; Release build; full headless test suite; lock drift rejection                                                                                      |
| Textual examples   | Example `pyproject.toml` and adjacent `uv.lock` files           | Textual resolves to `8.2.8`; manifests retain the compatible `>=0.80` floor while committed locks make CI and maintenance runs reproducible.                                                                                                                                                                                                        | Locked sync; Notes Showcase and Inspector lint, strict type checks, tests, and smoke runs                                                                          |
| TypeScript runtime | `langs/typescript/package-lock.json`; `package.json`            | Node is `>=20`; `rxjs` remains the sole reactive runtime; Ajv `8.20.0` validates the exported consumer-conformance schema and remains isolated from the root bundle; ESLint is `10.7.0`. TypeScript remains `5.9.3` because `@typescript-eslint` `8.64.0` supports TypeScript only below `6.1.0`, excluding current TypeScript 7.                   | `npm ci`; registry peer-range query; fixture sync; both typechecks; lint; build; test; dist-boundary test; lockfile audit                                          |
| React example      | Notes Showcase `package.json` and `package-lock.json`           | React and React DOM are `19.2.7`, Vite is `8.1.5`, `@vitejs/plugin-react` is `6.0.3`, ESLint is `10.7.0`, Testing Library is `16.3.2`, and jsdom `29.1.1` is the reviewed DOM runtime. Repository tests require Node 20.19+, 22.13+, or 24+; the published library retains its Node >=20 runtime floor.                                             | `npm ci`; audit; typecheck; ESLint; full Vitest suite; production build                                                                                            |
| Swift runtime      | `langs/swift/Package.swift`; `.github/workflows/swift.yml`      | Combine is the platform reactive primitive; package resources include all four fixtures; `swift-tools-version: 5.9` remains the resolver floor. GitHub's supported `macos-15` image runs the default compiler and the oldest hosted Xcode 16.0 compiler; separate generic-device builds compile the declared iOS 16, tvOS 16, and watchOS 9 floors. | Release build and parallel tests for root and nested packages on both compiler cells; code-signing-free `xcodebuild` for all three non-macOS platform destinations |
| Rust runtime       | `langs/rust/Cargo.toml`; `Cargo.lock`                           | `vmx-rs` is `0.25.0`, implements spec `3.22.0`, and has MSRV Rust `1.88`; runtime dependencies are the current stable `serde 1.0.228` and `thiserror 2.0.18`; the VMx-owned hot-stream facade has no `rxrust` dependency. Test-only floors are `serde_json 1.0.145` (locked to `1.0.150`) and `pretty_assertions 1.4.1`.                            | `cargo search <crate> --limit 1` for both runtime crates; format; locked clippy/tests/docs/package; disposable-consumer build; empty `cargo tree -i rxrust`        |
| Ratatui example    | TUI Showcase `Cargo.toml` and `Cargo.lock`                      | Ratatui `0.30.2` and crossterm `0.29.0` define the reviewed terminal frame, widget, layout, styling, event, and raw-mode contract on the Rust 1.88 floor.                                                                                                                                                                                           | Locked format/clippy/build/test; five VM-layer tests; non-interactive `--smoke` run; `cargo audit --deny warnings`                                                 |
| Shared contracts   | `spec/fixtures/*.json`; flavor copies; `spec/12-conformance.md` | Runtime copies remain byte-identical and all five flavors cover every library conformance ID.                                                                                                                                                                                                                                                       | fixture-sync tools and `tools/check-conformance-coverage.py --require` for all five flavors                                                                        |

## 3. Tooling and documentation contracts

| Area                         | Authoritative pin or source                                                   | Contract                                                                                                                                                                    | Executable evidence                                                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Python CI bootstrap          | `.github/workflows/python.yml`                                                | `astral-sh/setup-uv` is pinned to its `v8.3.2` commit; workflow uv is exactly `0.11.28`.                                                                                    | The 3-OS / 5-version Python matrix plus example jobs                                                                              |
| Docs dependencies            | `docs/requirements.in`; hash-locked `docs/requirements.txt`                   | The Python 3.12 docs environment installs only hash-verified resolutions; pytest is `9.1.1`, pip-audit is `2.10.1`, MkDocs Material is `9.7.7`, and Ruff is `0.15.22`.      | `pip install --require-hashes`; `python -m pip_audit --local`                                                                     |
| Three documentation surfaces | `docs/manifest.yaml`; `docs/content/**`                                       | Canonical Markdown generates in-repo navigation, the MkDocs `.io` site, and the GitHub wiki without source duplication.                                                     | `make docs-check`; strict MkDocs build; wiki dry-run/sync checks                                                                  |
| Documentation diagrams       | `docs/assets/diagrams/generate_diagrams.py`; `tools/generate-doc-diagrams.py` | Every maintained diagram has synchronized HTML/SVG/PNG output; repo-derived counts, text bounds, and raster exports are checked without mutating the worktree.              | Both generators with `--check`; `python -m scripts.docs.validate_diagrams`; diagram unit tests; original-resolution visual review |
| Rust advisory database       | `cargo-audit 0.22.2`; committed Rust lockfiles                                | RustSec vulnerabilities, unmaintained crates, unsound crates, and yanked releases fail both branch CI and the crates.io release gate.                                       | `cargo audit --file <Cargo.lock> --deny warnings` for the library and both executable examples                                    |
| GitHub Pages                 | `.github/workflows/docs.yml`                                                  | Build and pull-request jobs are read-only; only the deploy job receives `pages: write` and `id-token: write`.                                                               | `make docs-check`, artifact upload, then `actions/deploy-pages` on `main`                                                         |
| GitHub wiki                  | `.github/workflows/wiki.yml`; `scripts/docs/push_wiki.py`                     | `main` regenerates the wiki, validates diagrams, and pushes with the configured deploy key or scoped GitHub token fallback.                                                 | `push_wiki --check` dry-run before publication; `--check-published` read-only live comparison after publication                   |
| Local hygiene                | `.pre-commit-config.yaml`                                                     | Ruff covers library, tools, docs scripts, docs tests, and diagram generators; C# formatting reuses restored assets; Markdown formatting stays on canonical docs/spec paths. | `pre-commit run --all-files` after language dependencies are installed                                                            |

### 3.1 Immutable workflow action inventory

All remote actions are pinned to full commits. The upstream tag shown here was
resolved against the action repository on 2026-07-18; `dtolnay/rust-toolchain`
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
| `actions/setup-dotnet@a98b56852c35b8e3190ac28c8c2271da59106c68`             | `v6.0.0`              |
| `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020`               | `v7.0.0`              |
| `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1`             | `v6.3.0`              |
| `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`          | `v7.0.1`              |
| `actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9`    | `v5.0.0`              |
| `astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990`               | `v8.3.2`              |
| `codecov/codecov-action@fb8b3582c8e4def4969c97caa2f19720cb33a72f`           | `v7.0.0`              |
| `dtolnay/rust-toolchain@4cda84d5c5c54efe2404f9d843567869ab1699d4`           | `stable` (2026-07-16) |
| `googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7` | `v5.0.0`              |
| `pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b`      | `v1.14.0`             |
| `rust-lang/crates-io-auth-action@c6f97d42243bad5fab37ca0427f495c86d5b1a18`  | `v1.0.5`              |

The diagram jobs use `ubuntu-24.04` and install
`librsvg2-bin=2.58.0+dfsg-1build1` plus `pngquant=2.18.0-1build2`, the exact
Ubuntu Noble package revisions revalidated on 2026-07-14. This keeps SVG and
PNG export behavior reproducible instead of inheriting `ubuntu-latest` or
floating APT resolutions.

## 4. Release, registry, and identity contracts

| Channel     | Trigger and automation                                                                                                           | Authentication boundary                                                                                                                                                                                                 | Public verification                                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Release PRs | `release-please.yml` runs on `main`; `googleapis/release-please-action` is pinned to `45996ed1f6d02564a971a2fa1b5860e934307cf7`. | A fine-grained PAT or GitHub App credential in `RELEASE_PLEASE_TOKEN` creates PRs that trigger required CI; the workflow fails explicitly while that owner-created secret is absent. Human review gates the release PR. | Component-prefixed tag and release manifest agree with package/changelog versions.                                      |
| NuGet       | C# tag jobs in `release.yml` package all public projects.                                                                        | `nuget-csharp` environment approval plus `id-token: write`; `NuGet/login` exchanges GitHub OIDC under the owner-created nuget.org policy.                                                                               | Poll nuget.org, inspect package metadata/content, and install both `net8.0` and `netstandard2.0` in fresh consumers.    |
| PyPI        | `python-v*` tag produced by release-please.                                                                                      | `pypi-python` environment approval and PyPA trusted publishing; exact-pinned PEP 517 backend; local wheel install/smoke before upload; no repository API token.                                                         | Poll PyPI JSON, install the exact public version in a fresh environment, and verify imported version/min-spec metadata. |
| npm         | TypeScript tag job uses Node 24 and npm `11.5.1`.                                                                                | `npm-typescript` approval and OIDC trusted publishing; `NPM_TOKEN` is bootstrap-only.                                                                                                                                   | Poll the exact version under Node 20, 22, 24, and 26, exercise exports, and require provenance metadata.                |
| crates.io   | Rust tag job packages with the committed lock and MSRV.                                                                          | `crates-rust` approval; bootstrap token only for the first crate version, then the immutable `rust-lang/crates-io-auth-action` pin exchanges OIDC.                                                                      | Poll crates.io and docs.rs, then `cargo add vmx-rs@=X.Y.Z` and run fresh MSRV/stable consumers.                         |
| Swift       | Swift tags create GitHub releases; there is no central package upload.                                                           | A read-only verification job proves main ancestry, dual-tag equality, version parity, both packages, and a fresh public consumer; only its dependent release job receives job-scoped `contents: write`.                 | Resolve the exact tag through SwiftPM and build/test a fresh consumer.                                                  |

### 4.1 Live GitHub control state

The following owner-controlled settings were read through the GitHub API on
2026-07-18. They are deployment prerequisites or repository-policy gaps, not
source-code secrets, and maintenance must not silently claim that they are
configured:

| Control                          | Observed state                                                                                                                                                                                                                   | Required follow-up                                                                                                                                             |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nuget-csharp`                   | The environment has a required reviewer and exact `csharp-v*`, `csharp-notifications-v*`, and `csharp-dependency-injection-v*` tag policies, but permits self-review and has no `NUGET_USER` secret.                             | Disable self-review; add the nuget.org profile name only after its trusted-publishing policy is ready. C# publication remains blocked.                         |
| `pypi-python`                    | The environment has a required reviewer and exact `python-v*` tag policy, but `prevent_self_review` is `false`.                                                                                                                  | Disable self-review before the next upload.                                                                                                                    |
| `npm-typescript` / `crates-rust` | Both environments have required reviewers and exact release-tag policies, permit self-review, and have no bootstrap token.                                                                                                       | Disable self-review. The missing token is correct only after first publication and trusted-publisher setup; otherwise first publication remains owner-blocked. |
| `gitflow` ruleset                | `main` and `develop` reject deletion/non-fast-forward updates, require PRs, and require all ten stable CI contexts with strict up-to-date checks. Approvals, code-owner review, and resolved conversations remain at zero/false. | Decide whether human-review requirements should be raised; the automated merge gates are active.                                                               |
| `tag-integrity` ruleset          | All tags reject deletion and non-fast-forward updates. Tag creation remains available to the release workflows.                                                                                                                  | No source action; revalidate before releases.                                                                                                                  |
| Release Please credential        | Repository secrets currently contain no `RELEASE_PLEASE_TOKEN`; the workflow now fails clearly instead of creating a CI-bypassing PR with `GITHUB_TOKEN`.                                                                        | Create a least-privilege PAT or GitHub App token with contents/PR access and store it as `RELEASE_PLEASE_TOKEN`.                                               |
| Actions defaults                 | Default workflow permissions are read-only and workflows cannot approve pull requests.                                                                                                                                           | No action; retain the workflow-local write grants only where documented.                                                                                       |

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
