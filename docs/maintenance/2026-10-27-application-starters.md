# 1. Application Starters: Decision and Pilot

## 1.1. Status

| Field    | Value                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status   | Accepted for four channels: TypeScript Node, Python, Swift and React. C# and Rust stay deferred until their rows in §1.3 meet the gates.                         |
| Date     | 2026-10-27                                                                                                                                                       |
| Issue    | #410 (roadmap #323, finding E45, work order 910)                                                                                                                 |
| Baseline | `develop` at `b6a935ca`. Public packages on 2026-10-27: npm `@thekaveh/vmx` 3.30.0, `@thekaveh/vmx-react` 0.1.1, PyPI `vmx` 3.23.0, SwiftPM tag `swift-v3.24.0`. |
| Effect   | Tooling and CI only. This record changes no spec behavior, adds no conformance ID and needs no ADR.                                                              |

## 1.2. Decision

1. VMx ships starters as generator output, not as copied example trees. `tools/create-starter.py` writes each starter into an empty directory outside the checkout.
1. The generator installs the exact public package from the public registry. It then checks the lockfile, the resolved version, peer deduplication and the smoke test.
1. A channel gets a starter only after it has a public release. C# waits for #56 and Rust waits for #67.
1. TypeScript on Node without a UI was the first starter. Python, Swift and React followed after their channels passed the same gates.
1. A weekly, manual-dispatch CI job verifies every accepted starter. It never runs on pull requests, so it gates no merge.
1. The stop condition in §1.12 retires a starter when its upkeep costs more than it returns.

## 1.3. Channels and hosts

| Channel           | Public package (2026-10-27)                     | Host                                             | State                 |
| ----------------- | ----------------------------------------------- | ------------------------------------------------ | --------------------- |
| `typescript-node` | `@thekaveh/vmx` 3.30.0 (npm)                    | Node 22 and 24, no UI                            | Accepted; first pilot |
| `python-console`  | `vmx` 3.23.0 (PyPI)                             | CPython 3.10 to 3.14 console, venv in the target | Accepted; this record |
| `swift-package`   | `VMx` 3.24.0 (SwiftPM tags `v3.24.0`)           | macOS 13+ command-line package                   | Accepted; this record |
| `react-vite`      | `@thekaveh/vmx-react` 0.1.1 + core 3.30.0 (npm) | Vite 8 and React 19 in headless Chromium         | Accepted; this record |
| C#                | Not published                                   | .NET console                                     | Gated on #56          |
| Rust              | Not published                                   | Cargo binary                                     | Gated on #67          |

Each channel follows the same contract. It has `starters/<channel>/`, a verifier in the generator and one job in `starters.yml`.

## 1.4. Lockfile and registry policy

1. The repository tracks no starter lockfile. Each run resolves a fresh tree, so the weekly job sees upstream drift.
1. The generated starter keeps its lockfile, and its README tells the user to commit it.

The generator rejects any local, linked or foreign reference:

| Channel           | Lockfile                                             | Registry check                                                                                                           |
| ----------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `typescript-node` | `package-lock.json`                                  | No `file:` or `link:`; every `resolved` URL starts with `https://registry.npmjs.org/`                                    |
| `react-vite`      | `package-lock.json`                                  | The same scan as `typescript-node`                                                                                       |
| `python-console`  | `requirements.lock`, hash-pinned from the pip report | `pip install --report`: every download comes from `https://files.pythonhosted.org/`; no directory, VCS or direct URL     |
| `swift-package`   | `Package.resolved`                                   | Only one pin, `remoteSourceControl` at `https://github.com/thekaveh/VMx.git`; the version and the revision equal the tag |

1. npm installs run with `--ignore-scripts`. The TypeScript Node tree has no install script. The React tree has one, the optional macOS `fsevents` file watcher. Vite uses it only for the development server, so the build and the browser check pass without it. Vite 8 bundles with Rolldown, whose native binary comes as a prebuilt optional package. No esbuild or Rollup postinstall runs.
1. The Python channel installs from `--index-url https://pypi.org/simple` with `--no-cache-dir`. It uses no `--find-links`, no editable install and no path install.
1. The Python channel removes every `PIP_*`, `PYTHON*`, `UV_*`, virtual-environment and conda variable. It sets `PIP_CONFIG_FILE` to the null device. A user `pip.conf` or a `PYTHONPATH` into the checkout thus cannot leak in.
1. The Swift channel resolves with `--disable-dependency-cache`, so SwiftPM fetches from GitHub, not from a shared cache.
1. `git ls-remote` and every SwiftPM command run with `GIT_TERMINAL_PROMPT=0` and `GCM_INTERACTIVE=never`. They fail instead of waiting for a credential prompt.
1. Playwright's Chromium comes from Playwright's CDN, not from npm. It is the only download that does not come from a package registry.
1. `requirements.lock` matches only the CPython minor version that made it, because pip resolves for the running interpreter. For example, a lock made on 3.11 or later pins `reactivex` 6.1.0, which has no 3.10 release. The lock and the README both say so.

## 1.5. SwiftPM tag form

1. A Swift release has two tags on one commit. `swift-vX.Y.Z` starts the release workflow. `vX.Y.Z` is the semantic tag.
1. SwiftPM reads only semantic tags, so `swift-v3.24.0` is not a version to SwiftPM. `.package(url:, exact: "3.24.0")` resolves `v3.24.0`.
1. The release smoke consumer, `tools/smoke-swiftpm-consumer.py`, uses the same `exact:` form. The starter therefore follows what consumers use today.
1. The generator checks with `git ls-remote` that both tags name one commit. It then requires that `Package.resolved` names that commit.
1. Without `--version`, the generator picks the newest version that has both tags on one commit.

## 1.6. Platform prerequisites

1. The generator needs Python 3.10 or later and the standard library only. It needs no VMx build and no `dist` directory.
1. The generated project needs no VMx checkout beside it.
1. The TypeScript starter needs Node 22 or later and npm 10 or later. The VMx package floor stays Node 20.5, but Node 20 is past its end of life.
1. The Python starter needs CPython 3.10 or later. The generator creates `.venv` in the target with the interpreter that runs it.
1. The generator refuses an interpreter that is in the checkout, links into it or is a venv of it, such as `langs/python/.venv/bin/python`. `python -m venv` can link the new interpreter to the running one, which would tie the starter to the checkout. After it creates the venv, the generator checks that `.venv/bin/python` and the venv `home` resolve outside the checkout.
1. The Swift starter needs macOS 13 or later and a Swift 5.9 or later toolchain. VMx for Swift uses Combine, so the generator refuses other platforms. The smoke test is an executable target, so the Command Line Tools are enough. XCTest needs a full Xcode.
1. The React starter needs Node 22.12 or later, the Vite 8 floor. The browser check needs Playwright's Chromium headless shell. The generator installs it with the starter's own `playwright` devDependency. In CI, `--browser-deps` also installs Chromium's system packages.

## 1.7. Peer dependencies

1. A starter declares a peer directly when the app imports it. The TypeScript and React starters declare `rxjs ^7.8.0`, the VMx peer range.
1. The React starter declares the adapter peers with the adapter's ranges: `react ^19.0.0`, `react-dom ^19.0.0` and `use-sync-external-store ^1.6.0`. React 18 also satisfies the adapter, but the starter targets React 19.

The generator requires exactly one installed copy of each deduplicated package. It counts install locations in the lockfile.

| Channel           | Packages that must have one copy                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| `typescript-node` | `@thekaveh/vmx`, `rxjs`                                                                         |
| `react-vite`      | `@thekaveh/vmx`, `@thekaveh/vmx-react`, `react`, `react-dom`, `rxjs`, `use-sync-external-store` |

1. A second `rxjs` copy splits Observable identity between VMx and the app. A second React copy breaks hooks. The 2026-08-10 pilots found that directory links duplicated React (`docs/maintenance/2026-08-10-vmx-react-consumer-pilots.md` §5).
1. The dedup check fails before any smoke test runs. The browser check is a second guard: it fails on any console error or warning.
1. Unpublished React consumers pack, then install. A starter never links a source directory.
1. The Python starter imports only `vmx` and the standard library. `reactivex` comes from VMx, so `requirements.txt` pins only `vmx`.
1. `npm ls` exits non-zero on a missing or invalid peer. It thus also checks that the core pin satisfies the adapter's peer range.

## 1.8. Update policy

1. Without `--version`, the generator pins the newest public release: the npm `latest` dist-tag, the PyPI JSON `info.version`, or the newest Swift tag pair. The weekly job thus verifies each new release within a week.
1. For `react-vite`, `--version` pins the adapter and `--core-version` pins `@thekaveh/vmx`. Without them, both use the npm `latest` tag.
1. `--version X.Y.Z` reproduces a run for one exact version. The generator rejects ranges, tags and prerelease versions.
1. The generated README names the verified version, the toolchain and the platform. The generator writes it only after all checks pass.
1. Each README links a guide. TypeScript links `upgrading-typescript.md`. Python and Swift link their getting-started pages. React links the React integration page and the upgrade guide.
1. Each smoke test fails when the installed VMx version differs from the pin in the manifest.
1. `typescript ^6.0.3` follows the repository TypeScript line. `@types/node ^22.0.0` follows the Node 22 floor. The React starter uses `vite ^8.0.0`, `@vitejs/plugin-react ^6.0.0` and `playwright ^1.60.0`. A maintainer moves each range when its source moves.
1. The docs name a verified version only after a passing run against the public registry.

## 1.9. Template layout

The templates live in `starters/<channel>/` as real files. The generator renders only the manifest and `README.md`, because those carry the version.

| Channel           | Rendered manifest  | Copied sources                                                                                     |
| ----------------- | ------------------ | -------------------------------------------------------------------------------------------------- |
| `typescript-node` | `package.json`     | `src/notes.ts`, `src/main.ts`, `test/smoke.test.ts`, `tsconfig.json`                               |
| `python-console`  | `requirements.txt` | `notes_app/notes.py`, `notes_app/__main__.py`, `tests/test_smoke.py`                               |
| `swift-package`   | `Package.swift`    | `Sources/Notes/Notes.swift`, `Sources/NotesApp/main.swift`, `Sources/NotesSmoke/main.swift`        |
| `react-vite`      | `package.json`     | `src/notes.ts`, `src/App.tsx`, `src/main.tsx`, `e2e/browser-smoke.mjs`, Vite and TypeScript config |

This layout is easier to maintain than inline strings:

1. Editors and reviewers read real source with syntax highlighting.
1. The template sources hold no version, so a release needs no template edit.
1. A test pins each channel's file set and rejects hard-coded versions and local references.
1. The allowlist rejects any stray file in a template directory, including caches such as `__pycache__`, `.mypy_cache`, `node_modules` and `.build`. Do not build or run a starter inside `starters/`. To remove ignored files there, run `git clean -ndX starters/` to list them, then `git clean -fdX starters/`.
1. The repository tracks no `package.json`, `requirements.txt` or `Package.swift` in `starters/`. Dependabot and repository tooling therefore ignore the templates.
1. The React `src/notes.ts` is the same file as the TypeScript Node one. A test keeps them equal.

## 1.10. Clean-room CI

`.github/workflows/starters.yml` runs one job per channel.

| Job               | Runner          | Matrix               | Job timeout | Generator deadline |
| ----------------- | --------------- | -------------------- | ----------- | ------------------ |
| `typescript-node` | `ubuntu-latest` | Node 22 and 24       | 20 minutes  | 900 seconds        |
| `python-console`  | `ubuntu-latest` | Python 3.10 and 3.14 | 15 minutes  | 600 seconds        |
| `swift-package`   | `macos-15`      | Default Xcode        | 30 minutes  | 1500 seconds       |
| `react-vite`      | `ubuntu-latest` | Node 22 and 24       | 30 minutes  | 1500 seconds       |

1. Triggers: a weekly schedule and `workflow_dispatch` with optional exact versions per channel. No `push` or `pull_request` trigger exists.
1. Permissions: `contents: read`. The checkout keeps no credentials. Dispatch inputs reach the scripts only through `env`.
1. Isolation: the target is `mktemp -d` outside the workspace. `setup-node` runs with no package-manager cache, and pip runs with `--no-cache-dir`.
1. Pins: every action uses the commit SHA from the repository ledger.
1. Assertions: the lockfile or report scan, the pin check, the deduplication check, the smoke test and the entry point. React adds `npm run build` and the headless Chromium check.

## 1.11. Pilot evidence

All runs used the public registries on 2026-10-27 on macOS arm64 (Darwin 27.0).

The first GitHub run of the workflow was a manual dispatch on `develop` at `b984a518`, on 2026-10-27 ([run 40597946759](https://github.com/thekaveh/VMx/actions/runs/40597946759)). Every job passed:

| Job                                           | Result  |
| --------------------------------------------- | ------- |
| `typescript-node` (Node 22, Node 24)          | success |
| `python-console` (CPython 3.10, CPython 3.14) | success |
| `swift-package` (macOS)                       | success |
| `react-vite` (Node 22, Node 24, Chromium)     | success |

### 1.11.1. TypeScript Node

The first pilot ran on Node 26.12.1 and npm 11.20.0, and again on 2026-10-27 with the multi-channel generator.

| Check         | Result                                                                          |
| ------------- | ------------------------------------------------------------------------------- |
| Pin           | `@thekaveh/vmx` 3.30.0, the npm `latest` tag                                    |
| `npm ls`      | `@thekaveh/vmx` 3.30.0, `rxjs` 7.8.2, `typescript` 6.0.3, `@types/node` 22.20.5 |
| Lockfile      | 11 `resolved` URLs, all on the public registry; no `file:` or `link:`           |
| Deduplication | One `node_modules/@thekaveh/vmx`; one `node_modules/rxjs`                       |
| `npm test`    | 2 tests, 2 passed; exit 0                                                       |
| `npm start`   | Construct, edit, save, duplicate-title rejection, recovery, dispose; exit 0     |
| Node 22.23.4  | The same compiled smoke test and entry point passed; exit 0                     |

The smoke test covers construct, edit, command, error and dispose. It checks inline `executeAsync` rejection and the fire-and-forget `errors` channel. It checks that `construct()` after disposal throws `StatusTransitionError`.

### 1.11.2. Python console

| Check                 | Result                                                                                                         |
| --------------------- | -------------------------------------------------------------------------------------------------------------- |
| Pin                   | `vmx==3.23.0`, the PyPI latest release                                                                         |
| Interpreters          | CPython 3.10.12, 3.12.15 and 3.14.5; pip 26.2.2 in each venv                                                   |
| Install report        | `vmx` 3.23.0, `reactivex` 6.1.0 (5.1.0 on 3.10), `typing-extensions` 4.16.0; all from `files.pythonhosted.org` |
| `pip show vmx`        | `Version: 3.23.0`                                                                                              |
| Import location       | `vmx/__init__.py` inside the target `.venv`, with `-I` isolation                                               |
| Hostile env           | With `PYTHONPATH` at the checkout and `PIP_FIND_LINKS` set, `vmx` still imported from the target venv          |
| `requirements.lock`   | 3 hash-pinned lines for CPython 3.12; `pip install --require-hashes --dry-run` accepted it on 3.12             |
| `unittest`            | 2 tests, 2 passed; exit 0                                                                                      |
| `python -m notes_app` | Construct, edit, save, duplicate-title rejection, recovery, dispose; exit 0                                    |

The smoke test uses only the 3.23.0 API: `ComponentVMOf`, `CompositeVM`, a synchronous `RelayCommand` whose task error reaches the caller, and `StatusTransitionError` after disposal. The template passes `mypy --strict` against 3.23.0.

### 1.11.3. Swift package

| Check                  | Result                                                                                    |
| ---------------------- | ----------------------------------------------------------------------------------------- |
| Pin                    | `exact: "3.24.0"`, the newest Swift tag pair                                              |
| Tags                   | `v3.24.0` and `swift-v3.24.0` both name commit `36229cabfcc02734ce8378e9a6eaa64bb258491b` |
| `Package.resolved`     | One pin: `vmx`, `remoteSourceControl`, version 3.24.0, that revision                      |
| `show-dependencies`    | `vmx` 3.24.0 from `https://github.com/thekaveh/VMx.git`                                   |
| Toolchain              | Apple Swift 6.4, Command Line Tools only; `swift build` in 25 seconds                     |
| `swift run NotesSmoke` | 17 checks passed; exit 0                                                                  |
| `swift run NotesApp`   | Construct, edit, save, duplicate-title rejection, recovery, dispose; exit 0               |

The smoke test uses only the 3.24.0 API. It checks `VMxVersion.current` against the `Package.swift` pin, inline `executeAsync` errors, the `errors` channel of the fire-and-forget `execute()`, and `StatusTransitionError` after disposal.

### 1.11.4. React and Vite

| Check           | Result                                                                                                                                      |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Pins            | `@thekaveh/vmx-react` 0.1.1 and `@thekaveh/vmx` 3.30.0, the npm `latest` tags                                                               |
| `npm ls`        | `react` 19.3.1, `react-dom` 19.3.1, `rxjs` 7.8.2, `use-sync-external-store` 1.7.0, `vite` 8.3.5, `playwright` 1.64.1                        |
| Lockfile        | 60 lockfile entries, all resolved from the public registry; 36 installed on macOS; no `file:` or `link:`; `fsevents` install script skipped |
| Deduplication   | One copy each of `@thekaveh/vmx`, `@thekaveh/vmx-react`, `react`, `react-dom`, `rxjs`, `use-sync-external-store`                            |
| `npm run build` | `tsc` clean; Vite built 249 modules; exit 0                                                                                                 |
| Browser         | Headless Chromium 156.0.8078.4 on the `vite preview` server of `dist/`                                                                      |
| Browser checks  | 13 passed: version pin, construct, edit, Save disabled and enabled, save, error shown, recovery, dispose on unmount                         |
| Console         | No error or warning; no "Invalid hook call"                                                                                                 |
| Node 22.23.4    | npm 10.9.9; the same checks passed; exit 0                                                                                                  |

Two more checks ran by hand. A copy of React under the adapter's `node_modules` made the browser check fail with "Cannot read properties of null (reading 'useCallback')", the production form of an invalid hook call. The Vite development server under StrictMode ran the flow with no console problems.

## 1.12. Stop condition

The repository owner checks these conditions once per quarter, and when a starter job fails. Retire a starter, or stop adding channels, when any of these is true:

1. The starter needs more than two template fixes in one quarter. Count only the fixes whose pull request does not change a VMx package.
1. The weekly job fails three runs in a row, and no VMx package changed between those runs.
1. A release smoke consumer runs the same construct, edit, command, error and dispose flow on the same host.
1. No issue, discussion or consumer report cites the starter for two quarters. The clock starts on the merge date of the starter's first docs link.

To retire a starter, remove its job, its template directory and its docs link in one pull request. Record the reason in this file.

## 1.13. Delivery checklist (#323 §3)

| Checklist item                | These channels                                                                                                  |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Validate the consumer need    | #410 states the need: no proof that a fresh external project can run a published package.                       |
| Map affected flavors          | Affected: TypeScript, React adapter, Python and Swift consumers. Unaffected: every package source; C# and Rust. |
| Normative change              | None. No spec chapter, ADR or conformance ID changes.                                                           |
| Lifecycle guarantees          | Each smoke test asserts disposal and post-dispose `StatusTransitionError`. React asserts disposal on unmount.   |
| Fixtures                      | No fixture changes.                                                                                             |
| Documentation                 | The getting-started pages, the React page and the integration index name each verified version.                 |
| Docs gates                    | `make docs-check` passes locally.                                                                               |
| Public-package consumer tests | The generator is a public-package consumer test for each channel. §1.11 quotes the registry output.             |
| SemVer                        | No package version changes.                                                                                     |
| Close only when complete      | #410 stays open as partial. §1.14 lists the remaining channels.                                                 |

## 1.14. Remaining work

1. C#: after #56, add a console template and check `dotnet list package` for symbol and framework choice.
1. Rust: after #67, add a binary template and check `cargo tree` for crate and import naming.
