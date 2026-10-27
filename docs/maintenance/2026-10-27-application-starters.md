# 1. Application Starters: Decision and Pilot

## 1.1. Status

| Field    | Value                                                                                                                                                            |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status   | Accepted for one pilot channel. Other channels stay deferred until their rows in §1.3 meet the gates.                                                            |
| Date     | 2026-10-27                                                                                                                                                       |
| Issue    | #410 (roadmap #323, finding E45, work order 910)                                                                                                                 |
| Baseline | `develop` at `dfd8a50b`. Public packages on 2026-10-27: npm `@thekaveh/vmx` 3.30.0, `@thekaveh/vmx-react` 0.1.1, PyPI `vmx` 3.23.0, SwiftPM tag `swift-v3.24.0`. |
| Effect   | Tooling and CI only. This record changes no spec behavior, adds no conformance ID and needs no ADR.                                                              |

## 1.2. Decision

1. VMx ships starters as generator output, not as copied example trees. `tools/create-starter.py` writes each starter into an empty directory outside the checkout.
1. The generator installs the exact public package from the public registry. It then checks the lockfile, the resolved version, peer deduplication and the smoke test.
1. A channel gets a starter only after it has a public release. C# waits for #56 and Rust waits for #67.
1. The first and only accepted starter is TypeScript on Node without a UI. It is the cheapest host with a real published package.
1. A weekly, manual-dispatch CI job verifies every accepted starter. It never runs on pull requests, so it gates no merge.
1. The stop condition in §1.11 retires a starter when its upkeep costs more than it returns.

## 1.3. Channels and hosts

| Channel           | Public package (2026-10-27)                     | Host                           | State                                                  |
| ----------------- | ----------------------------------------------- | ------------------------------ | ------------------------------------------------------ |
| `typescript-node` | `@thekaveh/vmx` 3.30.0 (npm)                    | Node 22 and 24, no UI          | Pilot accepted; this record                            |
| React             | `@thekaveh/vmx-react` 0.1.1 + core 3.30.0 (npm) | Vite and React in a browser    | Next. Needs a real browser runtime, not only CI (#410) |
| Python            | `vmx` 3.23.0 (PyPI)                             | CPython 3.10+ console          | Next. Needs a template and a venv-based verifier       |
| Swift             | `VMx` 3.24.0 (SwiftPM tag)                      | macOS 13+ command-line package | Next. Needs a macOS runner                             |
| C#                | Not published                                   | .NET console                   | Gated on #56                                           |
| Rust              | Not published                                   | Cargo binary                   | Gated on #67                                           |

Each later channel follows the same contract. It adds `starters/<channel>/`, a verifier in the generator and one job in `starters.yml`.

## 1.4. Lockfile policy

1. The repository tracks no starter lockfile. Each run resolves a fresh tree, so the weekly job sees upstream drift.
1. The generated starter keeps its lockfile. The starter README tells the user to commit it.
1. The lockfile must have no `file:` or `link:` reference. Every `resolved` URL must start with the public registry URL.
1. The generator installs with `--ignore-scripts`. No package in the pilot tree needs an install script.

## 1.5. Platform prerequisites

1. The TypeScript starter needs Node 22 or later and npm 10 or later.
1. The VMx package floor stays Node 20.5. Node 20 is past its end of life, so the starter does not target it.
1. The generator needs Python 3.10 or later and the standard library only. It needs no VMx build and no `dist` directory.
1. The generated project needs no VMx checkout beside it.

## 1.6. Peer dependencies

1. The starter declares `rxjs` directly, because the app imports it. The range matches the VMx peer range, `^7.8.0`.
1. The generator requires exactly one installed copy of `@thekaveh/vmx` and one of `rxjs`. It counts install locations in the lockfile.
1. A second `rxjs` copy splits Observable identity between VMx and the app. The check fails before the smoke test runs.
1. A React starter must also require one copy of `react`. The 2026-08-10 pilots found that directory links duplicated React (`docs/maintenance/2026-08-10-vmx-react-consumer-pilots.md` §5).
1. Unpublished React consumers pack, then install. A starter never links a source directory.

## 1.7. Update policy

1. Without `--version`, the generator pins the npm `latest` dist-tag. The weekly job thus verifies each new release within a week.
1. `--version X.Y.Z` reproduces a run for one exact version. The generator rejects ranges, tags and prerelease versions.
1. The generated README names the verified version, Node, npm and platform. The generator writes it only after all checks pass.
1. The README links the upgrade guide, `docs/content/getting-started/upgrading-typescript.md`.
1. The starter smoke test fails when the installed VMx version differs from the `package.json` pin.
1. `typescript ^6.0.3` follows the repository TypeScript line. `@types/node ^22.0.0` follows the starter's Node 22 floor. A maintainer moves each range when its source moves.
1. The docs name a verified version only after a passing run against the public registry.

## 1.8. Template layout

The templates live in `starters/typescript-node/` as real files. The generator renders only `package.json` and `README.md`, because those carry the version.

This layout is easier to maintain than inline strings:

1. Editors and reviewers read real TypeScript with syntax highlighting.
1. The template sources hold no version, so a release needs no template edit.
1. A test pins the template file set and rejects hard-coded versions and local references.
1. The repository tracks no `package.json` in `starters/`, so Dependabot and repository npm tooling ignore the templates.

## 1.9. Clean-room CI

`.github/workflows/starters.yml` runs the generator on `ubuntu-latest` for Node 22 and 24.

1. Triggers: a weekly schedule and `workflow_dispatch` with an optional exact version. No `push` or `pull_request` trigger exists.
1. Permissions: `contents: read`. The checkout keeps no credentials.
1. Isolation: the target is `mktemp -d` outside the workspace. `setup-node` runs with no package-manager cache.
1. Pins: every action uses the commit SHA from the repository ledger.
1. Bounds: the job has a 20-minute timeout; the generator has a 900-second end-to-end deadline.
1. Assertions: lockfile scan, `npm ls` pin equality, one copy of each peer, `npm test` exit 0 and `npm start` exit 0.

## 1.10. Pilot evidence

The generator ran on 2026-10-27 on macOS arm64, Node 26.12.1, npm 11.20.0, against `https://registry.npmjs.org/`.

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

## 1.11. Stop condition

The repository owner checks these conditions once per quarter, and when a starter job fails. Retire a starter, or stop adding channels, when any of these is true:

1. The starter needs more than two template fixes in one quarter. Count only the fixes whose pull request does not change a VMx package.
1. The weekly job fails three runs in a row, and no VMx package changed between those runs.
1. A release smoke consumer runs the same construct, edit, command, error and dispose flow on the same host.
1. No issue, discussion or consumer report cites the starter for two quarters. The clock starts on the merge date of the starter's first docs link.

To retire a starter, remove its job, its template directory and its docs link in one pull request. Record the reason in this file.

## 1.12. Delivery checklist (#323 §3)

| Checklist item                | This pilot                                                                                |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| Validate the consumer need    | #410 states the need: no proof that a fresh external project can run a published package. |
| Map affected flavors          | Affected: TypeScript (pilot). Unaffected: C#, Python, Swift and Rust packages.            |
| Normative change              | None. No spec chapter, ADR or conformance ID changes.                                     |
| Lifecycle guarantees          | The smoke test asserts disposal order and post-dispose `StatusTransitionError`.           |
| Fixtures                      | No fixture changes.                                                                       |
| Documentation                 | One link in the TypeScript getting-started page names the verified version.               |
| Docs gates                    | `make docs-check` passes locally.                                                         |
| Public-package consumer tests | The generator is a public-package consumer test. §1.10 quotes the registry output.        |
| SemVer                        | No package version changes.                                                               |
| Close only when complete      | #410 stays open as partial. §1.13 lists the remaining channels.                           |

## 1.13. Remaining work

1. React: add a Vite and React template, require one `react` copy, and run it in a real browser runtime.
1. Python: add a console template, install `vmx==X.Y.Z` from PyPI in a fresh venv, and check `pip show vmx`.
1. Swift: add a SwiftPM executable template, resolve the exact tag, and check `swift package show-dependencies` on macOS.
1. C#: after #56, add a console template and check `dotnet list package` for symbol and framework choice.
1. Rust: after #67, add a binary template and check `cargo tree` for crate and import naming.
1. Link each accepted starter from `docs/content/integration/index.md` only after its channel passes against the public registry.
