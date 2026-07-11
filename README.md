# VMx

[![csharp](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml)
[![python](https://github.com/thekaveh/VMx/actions/workflows/python.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/python.yml)
[![typescript](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml)
[![swift](https://github.com/thekaveh/VMx/actions/workflows/swift.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/swift.yml)
[![rust](https://github.com/thekaveh/VMx/actions/workflows/rust.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/rust.yml)
[![conformance](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml)
[![spec-discipline](https://github.com/thekaveh/VMx/actions/workflows/spec-discipline.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/spec-discipline.yml)
[![examples](https://github.com/thekaveh/VMx/actions/workflows/examples-contract-checks.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/examples-contract-checks.yml)
[![release](https://github.com/thekaveh/VMx/actions/workflows/release.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/release.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A hierarchical, lifecycle-aware MVVM viewmodel framework — one language-neutral
specification with five idiomatic source flavors (C# / Python / TypeScript /
Swift / Rust). All five source flavors cover the 316 library conformance IDs;
the flagship example apps cover 5 additional THEME scenario IDs for **321
total** tracked scenarios.

## 0. Contents

1. [Overview](#1-overview)
1. [Architecture](#2-architecture)
   - 2.1 [Architecture diagram](#21-architecture-diagram)
   - 2.2 [Class diagram](#22-class-diagram)
   - 2.3 [Layers](#23-layers)
1. [Flavors](#3-flavors)
   - 3.1 [Versions and packages](#31-versions-and-packages)
   - 3.2 [Spec and flavor compatibility](#32-spec-and-flavor-compatibility)
1. [Getting started](#4-getting-started)
   - 4.1 [Install](#41-install)
   - 4.2 [Quickstart guides](#42-quickstart-guides)
   - 4.3 [Examples](#43-examples)
1. [Repository layout](#5-repository-layout)
   - 5.1 [Documentation map](#51-documentation-map)
1. [Versioning and conformance](#6-versioning-and-conformance)
   - 6.1 [SemVer policy](#61-semver-policy)
   - 6.2 [Conformance catalog](#62-conformance-catalog)
1. [Contributing](#7-contributing)
1. [License](#8-license)

## 1. Overview

VMx is a framework for building MVVM viewmodels with explicit lifecycle and
reactive messaging. It targets WPF / Avalonia / MAUI on .NET, Tkinter / PyQt /
NiceGUI / Textual on Python, and any DOM- or rxjs-based UI on TypeScript — but
makes no assumption about the UI layer. Every flavor exposes:

- A five-state construction lifecycle (`Destructed`, `Constructing`,
  `Constructed`, `Destructing`, plus terminal `Disposed`) with reversible
  `construct`/`destruct`, `reconstruct()`, and a synchronous depth-first
  `dispose()` cascade that can be invoked from any state.
- A reactive message hub for `PropertyChangedMessage` and
  `ConstructionStatusChangedMessage`, plus collection-change events on
  container VMs.
- Four hierarchy primitives — leaf `ComponentVM`, selectable `CompositeVM`,
  peer `GroupVM`, fixed-arity `AggregateVM1..6` — plus forwarding decorators
  for instrumentation.
- One shared VM collection capability for groups and composites, with
  selection layered only onto composites and atomic identity-preserving move.
- A `RelayCommand` with reactive `canExecute` triggers and explicit imperative
  re-evaluation notifications, plus v2.0 decorators
  (`CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`)
  and a modeled-CRUD helper (`ModeledCrudCommands`).
- Tree utilities (`walk`, `find`, `walk_expanded`) for introspection.
- 22 opt-in capability micro-interfaces (`ISelectable`, `IExpandable`,
  `IClosable`, `IFilterable`, `IPageable`, …) and helper state classes
  (`ExpandableState`, `SearchableState`) for layering behaviour onto VMs
  additively.
- `DerivedProperty<T>` for N-source computed values, `FormVM<T>` for
  snapshot/revert/validation flows, `DiscriminatorVM` for single-active-key
  coordination, `PagedComposition` / `TokenPagedComposition` for finite and
  cursor paging, an opt-in notification sub-package (`INotificationHub`),
  `IDialogService`, null-object service variants (`NullMessageHub`,
  `NullDispatcher`, `NullNotificationHub`, `NullLocalizer`,
  `NullDialogService`), and an `ILocalizer` hook for i18n.

The shape is identical across flavors; only the surface idiom changes
(PascalCase in C#, snake_case in Python, camelCase in TypeScript and Swift —
codified in ADR-0006).

## 2. Architecture

### 2.1 Architecture diagram

![VMx architecture diagram](assets/architecture.svg)

The diagram source is at [`assets/architecture.svg`](assets/architecture.svg);
a browsable HTML version with summary cards is at
[`assets/architecture.html`](assets/architecture.html), and a high-resolution
PNG export is at [`assets/architecture.png`](assets/architecture.png).

### 2.2 Class diagram

A cluster-level class map of the entire library — what every class family is, and how the families relate.

![VMx class diagram](assets/class-diagram.svg)

The diagram source is at [`assets/class-diagram.svg`](assets/class-diagram.svg);
a browsable HTML version with summary cards is at
[`assets/class-diagram.html`](assets/class-diagram.html), and a high-resolution
PNG export is at [`assets/class-diagram.png`](assets/class-diagram.png). Five bands:

1. **Lifecycle base** — `ComponentVMBase` + `ConstructionStatus`; every VM derives from here.
1. **VM family** — five idioms: leaf, composite (homogeneous + selectable), group (homogeneous peers), aggregate (heterogeneous, fixed arity 1..6), and specialized (`FormVM`, `DiscriminatorVM`, `NotificationVM`, `ConfirmationVM`, forwarding decorators).
1. **Commands & capabilities** — `RelayCommand` family + `DecoratorCommand` chain + `ModeledCrudCommands`, alongside the 22 capability micro-interfaces (Selection / Expansion / Lifecycle / Query / Dialog / CRUD).
1. **Services · Messages · State · Collections** — the constructor-injected runtime (`MessageHub`, `Dispatcher`, `ILocalizer`, `IDialogService` — each with its `Null*` sibling per ADR-0017), hub envelope types, state helpers (`SearchableState`, `ExpandableState`, `DerivedProperty`), observable collections, `PagedComposition`, `TokenPagedComposition`, filtered/scored composite views, fluent immutable builders, and tree utilities.
1. **Notifications sub-package (opt-in)** — `INotificationHub`, `ConfirmHelper`, bridged to `ConfirmationDecoratorCommand` in band 3 and to `NotificationVM` / `ConfirmationVM` in band 2.

Boxes are cluster-level (one box per related set of classes); the exhaustive member list lives in the linked spec chapters + ADRs.

### 2.3 Layers

Each flavor implements the same conceptual stack:

- **Spec** — `spec/` is the source of truth: 23 markdown chapters, 87 ADRs,
  4 JSON fixtures, 321 conformance IDs, version pinned in `spec/VERSION`.
- **Application code** — your host app instantiates VMs through builders.
- **Forwarding decorators** *(optional)* — `ForwardingComponentVM` and
  `ForwardingCompositeVM` wrap an inner VM for instrumentation, selective
  override, or composition.
- **Viewmodel hierarchy** — `ComponentVM<M>`, `CompositeVM<VM>`,
  `GroupVM<VM>`, `AggregateVM1..6`.
- **Commands** — `RelayCommand` and `RelayCommand<T>` with `execute`,
  `canExecute`, reactive trigger observables, and imperative re-evaluation
  notifications.
- **Messages and collection events** — `PropertyChangedMessage`,
  `ConstructionStatusChangedMessage`, `CollectionChangedEvent` with
  `BatchUpdate()`, atomic `Move`, and `AutoConstructOnAdd` options.
- **Tree utilities** — `walk(root)`, `walk_expanded(root)`, and
  `find(root, predicate)` over any VM hierarchy.
- **Services** — `MessageHub` (rx Subject-backed pub/sub) and
  `RxDispatcher` (paired foreground / background schedulers).
- **Lifecycle state machine** — orchestrates every VM; transitions enforced
  by a fixture-backed validator (`spec/fixtures/lifecycle-transitions.json`).
- **Builders** — immutable fluent setters that return new instances and
  validate required fields on `build()`.

## 3. Flavors

### 3.1 Versions and packages

| Flavor     | Source status           | Public package status                                          | Reactive primitive     |
| ---------- | ----------------------- | -------------------------------------------------------------- | ---------------------- |
| C#         | v3.7.0 in source        | NuGet package not published yet                                | System.Reactive        |
| Python     | v3.7.0 in source        | [`vmx`](https://pypi.org/project/vmx/) latest published: 3.1.0 | reactivex              |
| TypeScript | v3.7.0 in source        | npm package not published yet                                  | rxjs                   |
| Swift      | v3.7.0 in source        | SwiftPM tag not published yet; no central registry             | Combine                |
| Rust       | v0.7.0 in source        | crates.io package not published yet                            | VMx facade over rxrust |

`main` may contain an in-development source version before that version is
published to package registries. Use the compatibility matrix for source-level
spec parity; use each registry for installable package availability.

All five source flavors implement the 316 library conformance IDs. The flagship
example apps cover the 5 `THEME-00x` scenario IDs where a full UI host exists
(Swift via `examples/swift/notes-showcase/`, ADR-0067), bringing stable
UI-backed flavors to **321 total** tracked scenarios. See
[`langs/swift/README.md`](langs/swift/README.md) §5 for the Swift ID matrix.
The C# flavor multi-targets `netstandard2.0` and
`net8.0` and ships two companion assemblies:
[`VMx.Extensions.DependencyInjection`](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection/)
(`services.AddVMx(...)`) and
[`VMx.Notifications`](https://www.nuget.org/packages/VMx.Notifications/) (opt-in
`INotificationHub`). The Python flavor supports Python 3.10 through 3.13,
is `mypy --strict` clean, and exposes `vmx.notifications` as an opt-in
subpackage. The TypeScript flavor (npm package `@thekaveh/vmx` — renamed
in v2.4.0 because the unscoped `vmx` name was unavailable) targets Node
≥20, emits dual ESM + CJS bundles, and exposes `@thekaveh/vmx/notifications`
as a sub-path export. The Rust flavor lives under `langs/rust/` as the
`vmx-rs` crate with the `vmx` import namespace; it has full library conformance
coverage in source and is awaiting a crates.io release channel.

### 3.2 Spec and flavor compatibility

| spec  | csharp | python | typescript | swift          | rust          |
| ----- | ------ | ------ | ---------- | -------------- | ------------- |
| 3.7.x | 3.7.0  | 3.7.0  | 3.7.0      | 3.7.0          | 0.7.0         |
| 3.3.x | 3.3.0  | 3.3.0  | 3.3.0      | 3.3.0          | 0.3.0         |
| 3.2.x | 3.2.0  | 3.2.0  | 3.2.0      | 3.2.0          | 0.2.0         |
| 3.1.x | 3.1.0  | 3.1.0  | 3.1.0      | 3.1.0          | 0.1.0         |
| 2.6.x | 2.6.0  | 2.6.1  | 2.6.0      | 2.6.0 (subset) | —             |
| 2.4.x | 2.4.0  | 2.4.0  | 2.4.0      | 2.4.0 (subset) | —             |
| 2.3.x | 2.3.0  | 2.3.0  | 2.3.0      | —              | —             |
| 2.2.x | 2.2.0  | 2.2.0  | 2.2.0      | —              | —             |
| 2.1.x | 2.1.0  | 2.1.0  | 2.1.0      | —              | —             |
| 2.0.x | 2.0.0  | 2.0.0  | 2.0.0      | —              | —             |
| 1.0.x | 1.0.0  | 1.0.0  | —          | —              | —             |

See [`compatibility-matrix.md`](compatibility-matrix.md) for the full table.
Every published package declares its `MinSpecVersion` /
`__min_spec_version__` so the runtime can verify compatibility.

## 4. Getting started

### 4.1 Install

```bash
# C# (after the NuGet package is published)
dotnet add package VMx

# Python (latest public package may lag this source tree)
pip install vmx
# or
uv add vmx

# TypeScript (after the npm package is published)
npm install @thekaveh/vmx rxjs

# Rust (source-tree path dependency today)
cargo add vmx-rs --path langs/rust
```

### 4.2 Quickstart guides

- [`docs/getting-started/csharp.md`](docs/getting-started/csharp.md) — build a
  modeled `ComponentVM<UserModel>`, wire a `RelayCommand`, manage a
  `CompositeVM<TabVM>`.
- [`docs/getting-started/python.md`](docs/getting-started/python.md) — same
  shape, snake_case API, immediate / asyncio dispatchers.
- [`docs/getting-started/typescript.md`](docs/getting-started/typescript.md) —
  camelCase API, ESM imports, rxjs-backed observables.
- [`docs/getting-started/swift.md`](docs/getting-started/swift.md) —
  camelCase API, Combine-backed publishers, SwiftPM install (Swift flavor is
  at total parity as of v3.1.0; see `langs/swift/README.md` §5).
- [`langs/rust/README.md`](langs/rust/README.md) — Rust crate commands
  and a minimal `ComponentVm` example.

### 4.3 Examples

The four **flagship Notes Workspace** apps — one per language flavor, one
per UI framework — implement the same scenario from a single language-neutral
VM API surface, exercising **19 distinct VMx features** (notebooks tree,
paged + filterable notes list, strict `FormVM` editor with validation,
capability-aware action bar, notifications, async lifecycle, dialogs,
`AggregateVM6` root, the `ThemeVM` scenario contract, token-paged global
search, edit/preview `DiscriminatorVM`, and tag autocomplete via
`SearchableState`). See
[`examples/notes-showcase-parity.md`](examples/notes-showcase-parity.md) for
the cross-flavor feature matrix and
[`spec/proposals/2026-05-29-notes-showcase-scenario.md`](spec/proposals/2026-05-29-notes-showcase-scenario.md)
for the canonical scenario contract. The VM hierarchy is diagrammed at
[`examples/assets/notes-showcase-vm-hierarchy.svg`](examples/assets/notes-showcase-vm-hierarchy.svg);
the companion VMx component map is at
[`examples/assets/notes-showcase-vmx-components.svg`](examples/assets/notes-showcase-vmx-components.svg).

- [`examples/csharp/avalonia/NotesShowcase/`](examples/csharp/avalonia/NotesShowcase/)
  — Notes Workspace flagship on Avalonia 11 + .NET 8 (cross-platform XAML).
  Run: `dotnet run --project examples/csharp/avalonia/NotesShowcase`.
- [`examples/python/textual/notes_showcase/`](examples/python/textual/notes_showcase/)
  — Notes Workspace flagship on Textual ≥ 0.80 (TUI). Run:
  `uv run --project examples/python/textual/notes_showcase python -m notes_showcase`.
- [`examples/typescript/react/notes-showcase/`](examples/typescript/react/notes-showcase/)
  — Notes Workspace flagship on React 18 + Vite. Run: `npm ci && npm run dev`
  from the example dir; production bundle via `npm run build`.
- [`examples/swift/notes-showcase/`](examples/swift/notes-showcase/)
  — Notes Workspace flagship on SwiftUI + Combine (macOS). Build and test via
  `swift build` / `swift test` from the example dir (requires macOS + Xcode).
- [`examples/rust/tui/notes-showcase/`](examples/rust/tui/notes-showcase/)
  — Rust-native Ratatui showcase with a pure VMx MVVM layer. Smoke-run via
  `cargo run --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke`.
  The VM-layer diagram is
  [`docs/assets/diagrams/rust-tui-notes-showcase.svg`](docs/assets/diagrams/rust-tui-notes-showcase.svg).

Smaller per-flavor demos:

- [`examples/csharp/console/HelloVMx/`](examples/csharp/console/HelloVMx/) — console.
- [`examples/csharp/wpf/TodoApp/`](examples/csharp/wpf/TodoApp/) — WPF + MVVM
  (Windows only).
- [`examples/python/console/hello_vmx/`](examples/python/console/hello_vmx/) — console.
- [`examples/python/tk/todo_app/`](examples/python/tk/todo_app/) — Tkinter
  MVVM.
- [`examples/python/textual/inspector/`](examples/python/textual/inspector/) —
  Textual TUI inspector that introspects any VMx tree using
  `vmx.tree.walk`.
- [`examples/typescript/console/hello-vmx/`](examples/typescript/console/hello-vmx/) — minimal
  Node script.
- [`examples/rust/console/hello-vmx/`](examples/rust/console/hello-vmx/) —
  minimal Cargo console demo using `ComponentVm` and `RelayCommand`.

## 5. Repository layout

```
.
├── spec/                  language-neutral specification (source of truth)
│   ├── 00-overview.md ... 22-discriminator-vm.md   (23 chapters)
│   ├── ADRs/              architecture decision records (0001..0087)
│   ├── fixtures/          JSON test inputs shared across flavors
│   ├── proposals/         mostly historical; scenario contracts may be normative
│   └── VERSION            spec SemVer
├── langs/
│   ├── csharp/            VMx (NuGet) + VMx.Extensions.DependencyInjection + VMx.Notifications
│   ├── python/            vmx (PyPI)
│   ├── typescript/        @thekaveh/vmx (npm)
│   ├── swift/             VMx Swift Package (v3.7.0, total parity — 316 library + 5 THEME)
│   └── rust/              vmx-rs crate (source-tree only; crates.io pending)
├── examples/              runnable example apps per flavor
├── docs/getting-started/  per-flavor quickstart tutorials
├── docs/integration/      one-page UI-framework integration recipes
├── docs/maintenance/      maintenance run ledgers and audit records
├── tools/                 cross-cutting scripts (conformance coverage)
├── assets/                architecture + class diagrams, notes-showcase assets
├── .github/               issue/PR templates + CI workflows
└── compatibility-matrix.md
```

### 5.1 Documentation map

This README is the entry point; the documents below add focused detail.

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — spec / ADR / conformance workflow,
  per-flavor build commands, pre-commit setup. Read before opening a PR.
- [`SECURITY.md`](SECURITY.md) — supported-version table and how to report
  vulnerabilities.
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor-Covenant
  community guidelines.
- [`compatibility-matrix.md`](compatibility-matrix.md) — spec ↔ flavor
  version pairing.
- [`spec/README.md`](spec/README.md) — index of the 23 chapters, 87 ADRs,
  4 fixtures, and the 321-ID conformance catalog.
- [`spec/ADRs/README.md`](spec/ADRs/README.md) — ADR catalogue index.
- [`docs/content/primitives/disposal-contract.md`](docs/content/primitives/disposal-contract.md)
  — cross-flavor public disposal inventory and post-dispose contract.
- Per-flavor READMEs (status, install, API surface, dev commands):
  [`langs/csharp/README.md`](langs/csharp/README.md),
  [`langs/python/README.md`](langs/python/README.md),
  [`langs/typescript/README.md`](langs/typescript/README.md),
  [`langs/swift/README.md`](langs/swift/README.md) (v3.7.0, total parity — 316 library + 5 THEME),
  [`langs/rust/README.md`](langs/rust/README.md).
- Per-flavor CHANGELOGs (release history):
  [`langs/csharp/CHANGELOG.md`](langs/csharp/CHANGELOG.md),
  [`langs/python/CHANGELOG.md`](langs/python/CHANGELOG.md),
  [`langs/typescript/CHANGELOG.md`](langs/typescript/CHANGELOG.md),
  [`langs/swift/CHANGELOG.md`](langs/swift/CHANGELOG.md).
- Per-flavor release runbooks:
  [`langs/csharp/RELEASING.md`](langs/csharp/RELEASING.md) — NuGet release
  pipeline for `VMx` plus companion packages,
  [`langs/python/RELEASING.md`](langs/python/RELEASING.md) — PyPI release
  pipeline (`python-test` matrix gate → `pypi-python` environment approval →
  Trusted-Publishing-via-OIDC upload with Sigstore (PEP 740) attestations →
  `python-verify-published` fresh-venv smoke test → `python-release-notes`
  CHANGELOG-extracted GitHub Release),
  [`langs/typescript/RELEASING.md`](langs/typescript/RELEASING.md) — npm
  publish with provenance, and
  [`langs/swift/RELEASING.md`](langs/swift/RELEASING.md) — SwiftPM tag +
  GitHub Release flow. release-please currently automates Python routine
  version bumps + CHANGELOG entries via Conventional Commits.
- Per-flavor getting-started tutorials (longer walkthroughs):
  [`docs/getting-started/csharp.md`](docs/getting-started/csharp.md),
  [`docs/getting-started/python.md`](docs/getting-started/python.md),
  [`docs/getting-started/typescript.md`](docs/getting-started/typescript.md),
  [`docs/getting-started/swift.md`](docs/getting-started/swift.md).
- Per-flavor examples READMEs (run instructions):
  [`examples/csharp/README.md`](examples/csharp/README.md),
  [`examples/python/README.md`](examples/python/README.md),
  [`examples/typescript/README.md`](examples/typescript/README.md),
  [`examples/swift/notes-showcase/README.md`](examples/swift/notes-showcase/README.md),
  [`examples/rust/README.md`](examples/rust/README.md).
- [`examples/notes-showcase-parity.md`](examples/notes-showcase-parity.md) —
  cross-flavor parity matrix for all four flagship Notes-Showcase apps
  (Avalonia / Textual / React / SwiftUI); 19 spec features × 4 flavors, plus
  hierarchy and VMx-component diagrams.
- [`docs/integration/README.md`](docs/integration/README.md) — one-page
  integration recipes for 11 UI frameworks (WPF, MAUI, Avalonia, Textual,
  NiceGUI, Tkinter, React, Vue, Svelte, SolidJS, SwiftUI). Each recipe
  shows the framework-native binding + lifecycle + dispose pattern.
- [`docs/maintenance/2026-07-01-contract-ledger.md`](docs/maintenance/2026-07-01-contract-ledger.md) —
  external dependency and tool-contract checks recorded during the maintenance
  run.
- [`tools/README.md`](tools/README.md) — conformance-coverage tool and
  cross-cutting scripts.

## 6. Versioning and conformance

### 6.1 SemVer policy

Each language flavor versions independently in SemVer. The spec also versions
independently in SemVer. Every published package declares the spec version it
implements (`MinSpecVersion` in C#, `__min_spec_version__` in Python,
`__minSpecVersion__` in TypeScript, `VMxVersion.minSpecVersion` in Swift,
`MIN_SPEC_VERSION` in Rust). A
spec major bump triggers a major bump in every active flavor; a spec minor bump
(like v2.1.0) is fully backwards compatible and ships in flavors as a minor
bump.

### 6.2 Conformance catalog

`spec/12-conformance.md` enumerates 321 normative test scenarios keyed by ID
(`LIFE-001`, `HUB-007`, `COMP-013`, `UTIL-002`, `CAP-020`, `DPROP-012`,
`NOTIF-010`, `DIA-001`, `FORM-001`, `COL-001`, `HIER-001`, `AGG-006`,
`THEME-001`, …) — 316 library IDs plus 5 `THEME` scenario IDs. All five
flavors (C# / Python / TypeScript / Swift / Rust) implement the 316 library IDs under
their registered conformance suites (`langs/csharp/tests/VMx.Conformance.Tests`,
`langs/python/tests/conformance`, `langs/typescript/tests/conformance`, and
`langs/swift/Tests/VMxTests`, and `langs/rust/tests/conformance`), and
`tools/check-conformance-coverage.py` enforces 100% coverage in CI. Stable
flavors also cover the 5 `THEME-00x` scenario IDs via their respective flagship
example apps — Swift via `examples/swift/notes-showcase/` (ADR-0067). Every
stable flavor is at **total parity: 316 library + 5 THEME = 321**.

```bash
# Verify all full-parity flavors are at full catalog coverage
uv run --project langs/python python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript --require swift --require rust

# Report all registered flavors
python3 tools/check-conformance-coverage.py
```

## 7. Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the spec / ADR / conformance
workflow and per-flavor build instructions. The repository uses pre-commit
hooks (ruff, mdformat, dotnet format, eslint); install them with
`pre-commit install`.

## 8. License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
