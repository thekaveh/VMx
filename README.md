# VMx

[![csharp](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/csharp.yml)
[![python](https://github.com/thekaveh/VMx/actions/workflows/python.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/python.yml)
[![typescript](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/typescript.yml)
[![conformance](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml/badge.svg)](https://github.com/thekaveh/VMx/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A hierarchical, lifecycle-aware MVVM viewmodel framework — one language-neutral
specification, three idiomatic language flavors, 219 cross-language conformance
tests passing on every commit.

## Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
   - 2.1 [Diagram](#21-diagram)
   - 2.2 [Layers](#22-layers)
3. [Flavors](#3-flavors)
   - 3.1 [Versions and packages](#31-versions-and-packages)
   - 3.2 [Spec ↔ flavor compatibility](#32-spec--flavor-compatibility)
4. [Getting started](#4-getting-started)
   - 4.1 [Install](#41-install)
   - 4.2 [Quickstart guides](#42-quickstart-guides)
   - 4.3 [Examples](#43-examples)
5. [Repository layout](#5-repository-layout)
   - 5.1 [Documentation map](#51-documentation-map)
6. [Versioning and conformance](#6-versioning-and-conformance)
   - 6.1 [SemVer policy](#61-semver-policy)
   - 6.2 [Conformance catalog](#62-conformance-catalog)
7. [Contributing](#7-contributing)
8. [License](#8-license)

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
  peer `GroupVM`, fixed-arity `AggregateVM1..5` — plus forwarding decorators
  for instrumentation.
- A `RelayCommand` with reactive `canExecute` triggers, plus v2.0 decorators
  (`CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`)
  and a modeled-CRUD helper (`ModeledCrudCommands`).
- Tree utilities (`walk`, `find`, `walk_expanded`) for introspection.
- 22 opt-in capability micro-interfaces (`ISelectable`, `IExpandable`,
  `IClosable`, `IFilterable`, `IPageable`, …) and helper state classes
  (`ExpandableState`, `SearchableState`) for layering behaviour onto VMs
  additively.
- `DerivedProperty<T>` for N-source computed values, an opt-in notification
  sub-package (`INotificationHub`), null-object service variants
  (`NullMessageHub`, `NullDispatcher`, `NullNotificationHub`,
  `NullLocalizer`), and an `ILocalizer` hook for i18n.

The shape is identical across flavors; only the surface idiom changes
(PascalCase in C#, snake_case in Python, camelCase in TypeScript — codified in
ADR-0006).

## 2. Architecture

### 2.1 Diagram

![VMx architecture diagram](assets/architecture.svg)

The diagram source is at [`assets/architecture.svg`](assets/architecture.svg);
a browsable HTML version with summary cards is at
[`assets/architecture.html`](assets/architecture.html).

### 2.2 Layers

Each flavor implements the same conceptual stack:

- **Spec** — `spec/` is the source of truth: 22 markdown chapters, 33 ADRs,
  4 JSON fixtures, 219 conformance IDs, version pinned in `spec/VERSION`.
- **Application code** — your host app instantiates VMs through builders.
- **Forwarding decorators** *(optional)* — `ForwardingComponentVM` and
  `ForwardingCompositeVM` wrap an inner VM for instrumentation, selective
  override, or composition.
- **ViewModel hierarchy** — `ComponentVM<M>`, `CompositeVM<VM>`,
  `GroupVM<VM>`, `AggregateVM1..5`.
- **Commands** — `RelayCommand` and `RelayCommand<T>` with `execute`,
  `canExecute`, and reactive trigger observables.
- **Messages and collection events** — `PropertyChangedMessage`,
  `ConstructionStatusChangedMessage`, `CollectionChangedEvent` with
  `BatchUpdate()` and `AutoConstructOnAdd` options.
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

| Flavor     | Package                                                | Status   | Reactive primitive |
| ---------- | ------------------------------------------------------ | -------- | ------------------ |
| C#         | [`VMx`](https://www.nuget.org/packages/VMx/) on NuGet  | v2.1.0   | System.Reactive    |
| Python     | [`vmx`](https://pypi.org/project/vmx/) on PyPI         | v2.1.0   | reactivex          |
| TypeScript | [`vmx`](https://www.npmjs.com/package/vmx) on npm      | v2.1.0   | rxjs               |

The C# flavor multi-targets `netstandard2.0` and `net8.0` and ships two
companion assemblies:
[`VMx.Extensions.DependencyInjection`](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection/)
(`services.AddVMx(...)`) and `VMx.Notifications` (opt-in
`INotificationHub`). The Python flavor supports Python 3.10 through 3.13,
is `mypy --strict` clean, and exposes `vmx.notifications` as an opt-in
subpackage. The TypeScript flavor targets Node ≥18, emits dual ESM + CJS
bundles, and exposes `vmx/notifications` as a sub-path export.

### 3.2 Spec ↔ flavor compatibility

| spec  | csharp         | python         | typescript     |
| ----- | -------------- | -------------- | -------------- |
| 2.1.x | 2.1.0          | 2.1.0          | 2.1.0          |
| 2.0.x | 2.0.0          | 2.0.0          | 2.0.0          |
| 1.1.x | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  |
| 1.0.x | 1.0.0          | 1.0.0          | —              |

See [`compatibility-matrix.md`](compatibility-matrix.md) for the full table.
Every published package declares its `MinSpecVersion` /
`__min_spec_version__` so the runtime can verify compatibility.

## 4. Getting started

### 4.1 Install

```bash
# C#
dotnet add package VMx

# Python
pip install vmx
# or
uv add vmx

# TypeScript
npm install vmx
```

### 4.2 Quickstart guides

- [`docs/getting-started/csharp.md`](docs/getting-started/csharp.md) — build a
  modeled `ComponentVM<UserModel>`, wire a `RelayCommand`, manage a
  `CompositeVM<TabVM>`.
- [`docs/getting-started/python.md`](docs/getting-started/python.md) — same
  shape, snake_case API, immediate / asyncio dispatchers.
- [`docs/getting-started/typescript.md`](docs/getting-started/typescript.md) —
  camelCase API, ESM imports, rxjs-backed observables.

### 4.3 Examples

- [`examples/csharp/HelloVMx/`](examples/csharp/HelloVMx/) — console.
- [`examples/csharp/WpfTodoApp/`](examples/csharp/WpfTodoApp/) — WPF + MVVM
  (Windows only).
- [`examples/python/hello_vmx/`](examples/python/hello_vmx/) — console.
- [`examples/python/tk_todo_app/`](examples/python/tk_todo_app/) — Tkinter
  MVVM.
- [`examples/python/vmx_inspector/`](examples/python/vmx_inspector/) —
  Textual TUI inspector that introspects any VMx tree using
  `vmx.tree.walk`.
- [`examples/typescript/hello-vmx/`](examples/typescript/hello-vmx/) — minimal
  Node script.

## 5. Repository layout

```
.
├── spec/                  language-neutral specification (source of truth)
│   ├── 00-overview.md ... 21-collections.md   (22 chapters)
│   ├── ADRs/              architecture decision records (0001..0033)
│   ├── fixtures/          JSON test inputs shared across flavors
│   ├── proposals/         historical planning artifacts (not part of published docs)
│   └── VERSION            spec SemVer
├── langs/
│   ├── csharp/            VMx (NuGet) + VMx.Extensions.DependencyInjection + VMx.Notifications
│   ├── python/            vmx (PyPI)
│   └── typescript/        vmx (npm)
├── examples/              runnable example apps per flavor
├── docs/getting-started/  per-flavor quickstart tutorials
├── tools/                 cross-cutting scripts (conformance coverage)
├── assets/                architecture diagram (SVG + HTML)
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
- [`spec/README.md`](spec/README.md) — index of the 22 chapters, 33 ADRs,
  4 fixtures, and the 219-ID conformance catalog.
- [`spec/ADRs/README.md`](spec/ADRs/README.md) — ADR catalogue index.
- Per-flavor READMEs (status, install, API surface, dev commands):
  [`langs/csharp/README.md`](langs/csharp/README.md),
  [`langs/python/README.md`](langs/python/README.md),
  [`langs/typescript/README.md`](langs/typescript/README.md).
- Per-flavor CHANGELOGs (release history):
  [`langs/csharp/CHANGELOG.md`](langs/csharp/CHANGELOG.md),
  [`langs/python/CHANGELOG.md`](langs/python/CHANGELOG.md),
  [`langs/typescript/CHANGELOG.md`](langs/typescript/CHANGELOG.md).
- Per-flavor getting-started tutorials (longer walkthroughs):
  [`docs/getting-started/csharp.md`](docs/getting-started/csharp.md),
  [`docs/getting-started/python.md`](docs/getting-started/python.md),
  [`docs/getting-started/typescript.md`](docs/getting-started/typescript.md).
- Per-flavor examples READMEs (run instructions):
  [`examples/csharp/README.md`](examples/csharp/README.md),
  [`examples/python/README.md`](examples/python/README.md),
  [`examples/typescript/README.md`](examples/typescript/README.md).
- [`tools/README.md`](tools/README.md) — conformance-coverage tool and
  cross-cutting scripts.

## 6. Versioning and conformance

### 6.1 SemVer policy

Each language flavor versions independently in SemVer. The spec versions
independently in SemVer. Every published package declares the spec version it
implements (`MinSpecVersion` in C#, `__min_spec_version__` in Python,
`__minSpecVersion__` in TypeScript). A spec major bump triggers a major bump
in every active flavor; a spec minor bump (like v2.1.0) is fully backwards
compatible and ships in flavors as a minor bump.

### 6.2 Conformance catalog

`spec/12-conformance.md` enumerates 219 normative test scenarios keyed by ID
(`LIFE-001`, `HUB-007`, `COMP-013`, `UTIL-002`, `CAP-020`, `DPROP-012`,
`NOTIF-010`, `DIA-001`, `FORM-001`, `COL-001`, …). Every flavor re-implements the catalog under
`langs/<flavor>/tests/conformance/`, and `tools/check-conformance-coverage.py`
enforces 100% coverage in CI.

```bash
# Verify all three flavors are at full coverage
uv run --project langs/python python tools/check-conformance-coverage.py \
    --require csharp --require python --require typescript
```

## 7. Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the spec / ADR / conformance
workflow and per-flavor build instructions. The repository uses pre-commit
hooks (ruff, mdformat, dotnet format); install them with
`pre-commit install`.

## 8. License

MIT — see [`LICENSE`](LICENSE).
