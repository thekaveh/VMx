# VMx Phase 1 — Spec v1.0.0 Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author the complete language-neutral VMx specification (`spec/00-overview.md` through `spec/12-conformance.md`), the seven foundational ADRs, the three JSON fixtures, the cross-language conformance coverage tool, the wire-up of the two conformance/spec-discipline CI workflows to actually enforce their rules, and tag `spec-v1.0.0`. After Phase 1, the spec is the contract that Phase 2 (C# v1.0) and Phase 3 (Python v1.0) implement against.

**Architecture:** Phase 1 is documentation + one small Python script. Spec files are markdown. JSON fixtures encode the parts of the spec that need to be machine-checkable (the lifecycle transition matrix, message-ordering invariants, command truth table). The conformance catalog (`spec/12-conformance.md`) enumerates ~60 stable `XXX-NNN` IDs with Given/When/Then prose; future language flavors must each have a matching test for every ID. The CI tool (`tools/check-conformance-coverage.py`) parses the catalog and reports gaps in any active language's `tests/conformance/` directory.

**Tech Stack:**

- **Markdown** (CommonMark + GFM tables, mdformat-validated)
- **JSON** (data fixtures)
- **Python 3.10+** for the tooling script + `pytest` for its unit tests (reuses the existing `langs/python` test infrastructure for the tool's own tests, but the tool itself lives in `tools/`)
- **GitHub Actions YAML** (already configured by Phase 0; we wire up the real logic here)
- **Git tags** for `spec-v1.0.0`

**Spec reference:** `/Users/kaveh/repos/VMx/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md` §5 (spec contents), §6 (cross-language conformance), §12.1 (Phase 1 deliverables list).

**Working directory for all relative paths:** `/Users/kaveh/repos/VMx`

**Phase 0 prerequisite verified:** The repo at HEAD (`main` branch, commit `6839e04` or descendant) has:

- `spec/`, `spec/ADRs/`, `spec/fixtures/`, `tools/` directories present (some with `.gitkeep` placeholders).
- `langs/python/` and `langs/csharp/` scaffolded with smoke tests passing.
- Five GitHub Actions workflows present (`python.yml`, `csharp.yml`, `docs.yml`, `conformance.yml`, `spec-discipline.yml`).
- pre-commit hooks active (`ruff`, `mdformat`, `dotnet format`, hygiene).
- `compatibility-matrix.md` placeholder at the repo root.

If any of the above is not true, STOP and address before proceeding.

______________________________________________________________________

## Pre-flight

Run from `/Users/kaveh/repos/VMx`:

```bash
git status
git log --oneline -3
git rev-parse --abbrev-ref HEAD
```

Expected:

- Branch `main` (or a fresh feature branch off `main`).
- Working tree clean.
- HEAD shows commit `6839e04 chore: tighten .gitignore and add docs.yml TODO` or a descendant.

**Tools required** (verify before starting):

```bash
git --version          # any 2.30+
python3 --version      # 3.10+
uv --version           # for running pytest on the tool tests
pre-commit --version
```

**Recommended branch strategy:** Create `feat/phase-1-spec-v1` and do all work there. Merge to `main` at the end (Task 14).

```bash
cd /Users/kaveh/repos/VMx
git checkout -b feat/phase-1-spec-v1
```

______________________________________________________________________

## File structure produced by Phase 1

```
VMx/
├── spec/
│   ├── README.md                                  KEEP (Phase 0 placeholder; updated in Task 1)
│   ├── VERSION                                    NEW (single line: 1.0.0)
│   ├── 00-overview.md                             NEW
│   ├── 01-concepts.md                             NEW
│   ├── 02-lifecycle.md                            NEW
│   ├── 03-messages.md                             NEW
│   ├── 04-commands.md                             NEW
│   ├── 05-component-vm.md                         NEW
│   ├── 06-composite-vm.md                         NEW
│   ├── 07-group-vm.md                             NEW
│   ├── 08-aggregate-vm.md                         NEW
│   ├── 09-forwarding.md                           NEW
│   ├── 10-builders.md                             NEW
│   ├── 11-threading.md                            NEW
│   ├── 12-conformance.md                          NEW (the catalog)
│   ├── ADRs/
│   │   ├── 0001-drop-comscore.md                  NEW
│   │   ├── 0002-rx-as-reactive-primitive.md       NEW
│   │   ├── 0003-constructor-injection.md          NEW
│   │   ├── 0004-langs-folder-layout.md            NEW
│   │   ├── 0005-drop-virtualization-from-core.md  NEW
│   │   ├── 0006-idiomatic-api-per-language.md     NEW
│   │   └── 0007-aggregate-vm-arity-1-to-5.md      NEW
│   └── fixtures/
│       ├── lifecycle-transitions.json             NEW
│       ├── message-ordering.json                  NEW
│       └── command-truthtable.json                NEW
├── tools/
│   ├── README.md                                  MODIFIED (point at the now-existing tool)
│   ├── check-conformance-coverage.py              NEW
│   └── tests/
│       ├── __init__.py                            NEW (empty)
│       ├── conftest.py                            NEW
│       └── test_check_conformance_coverage.py     NEW
├── .github/workflows/
│   ├── conformance.yml                            MODIFIED (real enforcement)
│   └── spec-discipline.yml                        MODIFIED (real enforcement)
├── compatibility-matrix.md                        MODIFIED (add row for spec 1.0)
└── (tag) spec-v1.0.0                              NEW
```

`spec/ADRs/.gitkeep` and `spec/fixtures/.gitkeep` are deleted in the relevant tasks once their parent directories are no longer empty.

______________________________________________________________________

## Task 1 — Foundation: spec/VERSION + ADRs 0001–0007

ADRs come before the spec prose because they record the *why* behind the choices the spec encodes. The spec text references the ADR numbers, so we write the ADRs first.

**Files:**

- Create: `spec/VERSION` (single line)
- Create: 7 files under `spec/ADRs/`
- Delete: `spec/ADRs/.gitkeep`

### Step 1.1: `spec/VERSION`

Create `/Users/kaveh/repos/VMx/spec/VERSION` with exactly:

```
1.0.0
```

(No trailing whitespace beyond the final newline. This is the spec's own SemVer per the design doc §7.)

### Step 1.2: ADR 0001 — Drop comScore

Create `/Users/kaveh/repos/VMx/spec/ADRs/0001-drop-comscore.md`:

```markdown
# ADR 0001 — Drop the comScore.Services dependency

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

The legacy VMx (`/Users/kaveh/repos/dotnet-tag/src/DotNetTag/VMx/`) depended on `comScore.Services` for its service-locator pattern: every `ComponentVM` accepted an `SL : IVMxServiceLocator` generic parameter and retrieved `IMessageHub`, `TaskScheduler`, and `IConstants` from it. `comScore.Services` is an internal library not suitable for an open-source release.

## Options considered

1. **Vendor a minimal slice of comScore.Services into the new repo.** Preserves the legacy API but ships private code under a new name.
2. **Re-implement a thin in-repo locator.** Re-creates the locator pattern under a VMx-owned namespace.
3. **Eliminate the locator entirely; use constructor injection.** VMs receive `IMessageHub` and `IDispatcher` via constructor arguments (and via the builder for fluent users).

## Decision

Option 3. Constructor injection is idiomatic in modern .NET (`Microsoft.Extensions.DependencyInjection` and similar), idiomatic in Python (explicit dependencies via `__init__`), and removes a class of "where does this come from" ambiguity. The locator generic parameter goes away, simplifying the heaviest type signatures.

## Consequences

- Public VM constructors and builders gain explicit `IMessageHub` / `IDispatcher` arguments.
- The `ComponentVMBase<SL, …>` generic parameter `SL` disappears across all base classes.
- An optional `VMx.Extensions.DependencyInjection` companion package wires `IMessageHub` + `IDispatcher` into Microsoft.Extensions.DependencyInjection for users who want the convenience.
- The Python flavor's equivalent companion is left for Phase 3 (it has fewer DI conventions to integrate with; explicit constructor args suffice).
```

### Step 1.3: ADR 0002 — Rx as reactive primitive

Create `/Users/kaveh/repos/VMx/spec/ADRs/0002-rx-as-reactive-primitive.md`:

```markdown
# ADR 0002 — Rx is the reactive primitive

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx is built around a hot stream of `IMessage` events (the message hub) and observable command triggers (`IObservable<Unit>` re-evaluating `CanExecute`). The legacy library used System.Reactive 2.2.5. We need a reactive primitive that is available, mature, and semantically consistent across C#, Python, and future TypeScript / Kotlin / Swift.

## Options considered

1. **Native async/events first; optional Rx adapter package.** Core API uses C# `async`/`Task`/`IAsyncEnumerable`, Python `asyncio`/`AsyncIterator`, etc. A separate Rx adapter is published for users who want richer operators.
2. **A custom in-house observer abstraction (`IObservable<T>`-like) with no operator library.** Zero external dependencies, predictable cross-language behavior, but reinvents what Rx already provides.
3. **Standardize on Rx in every language.** System.Reactive (C#), reactivex (Python), rxjs (TypeScript), kotlinx.coroutines.flow or RxKotlin (Kotlin), Combine or RxSwift (Swift).

## Decision

Option 3. Rx ports exist and are stable in every language we care about. The operator library (Where, Select, Throttle, ObserveOn, …) is industry-standard for reactive MVVM, and we get it for free in each flavor instead of re-implementing or omitting.

## Consequences

- Every active language flavor depends on its language's Rx port (mandatory in `pyproject.toml` / `Directory.Packages.props` / `package.json`).
- A new language flavor cannot be added unless a comparable Rx port exists; the playbook (§13 of the design doc) calls this out as the first gate. Languages without an Rx port (e.g., Rust, Go) require an ADR documenting the semantic mapping before they can join.
- Conformance tests pin Rx-specific semantics (hot streams, no replay, scheduler-aware delivery) so language ports cannot drift on these.
```

### Step 1.4: ADR 0003 — Constructor injection

Create `/Users/kaveh/repos/VMx/spec/ADRs/0003-constructor-injection.md`:

```markdown
# ADR 0003 — Constructor injection over service locator

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0
**Related:** ADR-0001

## Context

Independent of dropping comScore (ADR-0001), we need to decide *how* VMs receive their cross-cutting dependencies (`IMessageHub`, `IDispatcher`). The legacy locator pattern centralizes lookup but couples VMs to a runtime registry and complicates testing.

## Options considered

1. **Built-in minimal service locator.** Ship a `VMxContext` or ambient locator that VMs default to. Closer to the legacy API; convenient for quick starts.
2. **Constructor injection only.** VMs accept dependencies as explicit constructor arguments (and via the builder fluent API). The user wires them up — directly, through their DI container, or via the optional `VMx.Extensions.DependencyInjection` package.
3. **Both.** Constructor injection primary, optional locator helper.

## Decision

Option 2. Constructor injection is testable, explicit, and removes the ambient-state failure mode where a forgotten registration produces a confusing null reference deep in a VM's lifecycle. Modern .NET and modern Python both treat constructor injection as the default; we follow the convention.

## Consequences

- All builders include `Services(IMessageHub, IDispatcher)` (or equivalent per language) as a required call before `Build()`.
- The conformance catalog includes `BLD-002` (required-field validation) covering missing `IMessageHub` / `IDispatcher` at `build()` time.
- An optional companion package per language registers the services with the host's DI container as a convenience.
```

### Step 1.5: ADR 0004 — langs/ folder layout

Create `/Users/kaveh/repos/VMx/spec/ADRs/0004-langs-folder-layout.md`:

```markdown
# ADR 0004 — `langs/<lang>/` repo layout

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx is a single semantic library shipped in multiple language flavors. The repo must keep flavors isolated (no cross-language imports) while sharing the spec and CI. Three reasonable layouts:

## Options considered

1. **Top-level language folders** (`csharp/`, `python/`, …). Short paths; signals nothing about multi-language structure.
2. **`langs/<lang>/`** umbrella. Each flavor self-contained under `langs/`; root reserved for cross-cutting concerns (`spec/`, `docs/`, `examples/`, `tools/`, `.github/`).
3. **Per-package nesting** (`packages/csharp-vmx/`, `packages/csharp-vmx-rx/`, …). Scales if one flavor ships many sub-packages; over-engineered for our 1–2 packages per flavor.

## Decision

Option 2. `langs/<lang>/` makes the multi-language intent visible at the root and isolates each flavor's build/test/release artifacts. Adding a new language is purely additive: drop `langs/<lang>/` in with its own project file, no other directories need to change.

## Consequences

- All language-specific code, configuration, and tests live under `langs/<lang>/`.
- Cross-cutting concerns (`spec/`, `docs/`, `examples/`, `tools/`, `.github/`) live at the root.
- CI workflows trigger on path filters matching `langs/<lang>/**` and `spec/**`.
- Per-language `CHANGELOG.md` and `README.md` live alongside each `langs/<lang>/` to keep flavor-local context flavor-local.
```

### Step 1.6: ADR 0005 — Drop virtualization from core

Create `/Users/kaveh/repos/VMx/spec/ADRs/0005-drop-virtualization-from-core.md`:

```markdown
# ADR 0005 — Drop virtualization from the core library

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

The legacy `CompositeVM` used `AlphaChiTech.VirtualizingObservableCollection` for paged virtualization of large child lists. The dependency is tied to WPF's `ItemsControl` virtualization, has not been updated since 2017, and has no direct equivalent in Python or TypeScript.

## Options considered

1. **Keep paged virtualization in core.** Replace AlphaChiTech with a modern equivalent (e.g., DynamicData, or a custom paged collection). Preserves behavior parity but ports awkwardly across languages.
2. **Drop from core; optional adapter package planned for later.** Core `CompositeVM` exposes `IList<VM>` + `INotifyCollectionChanged`. An optional `VMx.Virtualization` package can ship later for users who want paged behavior.
3. **Drop permanently.** Users handle virtualization at the UI layer themselves; we never ship it.

## Decision

Option 2. Virtualization is a UI-layer concern — WPF, Avalonia, and MAUI each have their own item virtualization. Putting it in the core couples the spec to one platform's primitives. A future optional adapter can ship if demand surfaces.

## Consequences

- `CompositeVM<VM>` (and modeled variant) exposes only `IList<VM>` + `INotifyCollectionChanged`-equivalent semantics; no paging.
- No `VMx.Virtualization` package ships in 1.0; it's a post-1.0 follow-on.
- Existing legacy users migrating to the new library who relied on virtualization must wire it at their UI layer or wait for the adapter package.
```

### Step 1.7: ADR 0006 — Idiomatic API per language

Create `/Users/kaveh/repos/VMx/spec/ADRs/0006-idiomatic-api-per-language.md`:

```markdown
# ADR 0006 — Idiomatic API per language, conceptual parity enforced by spec

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx ships in C#, Python, and future TypeScript. Two naming/structure philosophies are possible.

## Options considered

1. **Literal mirror across languages.** Python `ComponentVM.Construct(...)` mirrors C# `ComponentVM.Construct(...)` exactly. Pro: identical docs for any flavor. Con: violates Python and TS conventions; Python developers expect `snake_case` member names.
2. **Idiomatic per language; conceptual parity only.** C# `PascalCase`, Python `snake_case`, TS `camelCase`. Same concepts and semantics, native-feeling surfaces. Cross-language conformance enforced by the conformance catalog rather than by name-matching.
3. **Idiomatic primary + thin alias layer for literal mirroring.** Provide both `component_vm.construct()` (idiomatic) and `componentVM.Construct()` (alias) in non-C# flavors. Doubles surface area.

## Decision

Option 2. Each language flavor follows its language's conventions for casing, fluent vs. factory style, async semantics, and idiom-specific patterns (e.g., Python `@dataclass(frozen=True)` builders, C# `record`-based messages). Semantic parity is the spec's responsibility, enforced by the conformance test catalog.

## Consequences

- Names differ across flavors but concepts do not. The spec describes concepts (`ComponentVM`, `Construct`) without prescribing casing.
- Each flavor's `README.md` documents its native idioms.
- Conformance tests share stable `XXX-NNN` identifiers but each language implements them in its native test framework.
- A divergence beyond casing/idiom (e.g., "Python has a `select_all` that C# does not") requires an ADR documenting the why.
```

### Step 1.8: ADR 0007 — AggregateVM arity 1-to-5

Create `/Users/kaveh/repos/VMx/spec/ADRs/0007-aggregate-vm-arity-1-to-5.md`:

```markdown
# ADR 0007 — `AggregateVM` covers arities 1 through 5

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

`AggregateVM<VM1..VMN>` represents a fixed tuple of heterogeneous child VMs. The legacy library exposed arities 1 through 5. We need to decide the upper bound for v1.0 and whether to use variadic generics where the language supports them.

## Options considered

1. **Arities 1–5 (legacy parity), explicit per-arity classes.** Same as legacy. Predictable, no language-specific tricks.
2. **Variadic generics in languages that support them.** C# 13+ does not support variadic generics natively; Python 3.11+ does (`TypeVarTuple`). Asymmetric across languages.
3. **A single `AggregateVM<VM*>` with runtime arity.** Loses compile-time type safety in C#; not idiomatic in either language.

## Decision

Option 1. Five explicit classes per language. The arity cap of 5 is a soft signal: when more than 5 heterogeneous children are needed, the right answer is usually a `CompositeVM<VM>` or `GroupVM<VM>` with homogeneous children. C# cannot express variadic generics, so the asymmetric option (2) would break the symmetric-spec goal stated in ADR-0006.

## Consequences

- `AggregateVM1` through `AggregateVM5` exist in every language flavor.
- Beyond arity 5, users compose multiple aggregates or switch to composite/group.
- The conformance catalog covers each arity (`AGG-001` through `AGG-005`).
- A future spec major version could lift the cap; that would be a v2.0 change.
```

### Step 1.9: Clean up `.gitkeep`

```bash
cd /Users/kaveh/repos/VMx
git rm spec/ADRs/.gitkeep
```

### Step 1.10: Update `spec/README.md`

Open `/Users/kaveh/repos/VMx/spec/README.md`. Replace the entire content with:

```markdown
# spec/

The language-neutral specification of VMx. Source of truth for every language flavor.

This directory is the contract. Every published package (C# `VMx`, Python `vmx`, future
TypeScript `vmx`) declares the spec version it implements. Conformance tests under
`langs/<lang>/tests/conformance/` re-implement the catalog at `12-conformance.md` and
must pass before any flavor releases a stable version.

## Contents

- `00-overview.md` — vision, scope, glossary.
- `01-concepts.md` — VM hierarchy, MVVM role, dependency philosophy.
- `02-lifecycle.md` — `ConstructionStatus` state machine and invariants.
- `03-messages.md` — message hub semantics, ordering, threading.
- `04-commands.md` — command contract, predicates, reactive triggers.
- `05-component-vm.md` — `ComponentVM` (readonly and modeled variants).
- `06-composite-vm.md` — `CompositeVM` (selectable children, `Current`).
- `07-group-vm.md` — `GroupVM`.
- `08-aggregate-vm.md` — `AggregateVM<VM1..VM5>` and arity rationale.
- `09-forwarding.md` — forwarding decorators.
- `10-builders.md` — builder semantics (immutability, fluent flow).
- `11-threading.md` — foreground/background and scheduler contract.
- `12-conformance.md` — cross-language conformance test catalog.
- `VERSION` — current spec SemVer.
- `fixtures/` — machine-checkable test inputs (JSON).
- `ADRs/` — Architecture Decision Records.

## Versioning

Spec version is tracked in `VERSION` and follows SemVer. Each language flavor declares
the spec version it implements (see `compatibility-matrix.md`). Breaking spec changes
require a major-version bump in every active flavor.

See the design doc at `../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`
for the full background.
```

### Step 1.11: Verify pre-commit passes

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/VERSION spec/README.md spec/ADRs/*.md
```

Expected: all hooks pass (mdformat may reformat slightly; if so, stage the changes).

### Step 1.12: Commit

```bash
cd /Users/kaveh/repos/VMx
git add spec/VERSION spec/README.md spec/ADRs/
git commit -m "docs(spec): add ADRs 0001-0007 and VERSION file

Foundation for spec v1.0.0. Seven ADRs document the architectural choices
that the spec text encodes:
- 0001: drop comScore.Services dependency
- 0002: Rx as the reactive primitive across all languages
- 0003: constructor injection over service locator
- 0004: langs/<lang>/ repo layout
- 0005: drop virtualization from the core library
- 0006: idiomatic API per language, parity via conformance catalog
- 0007: AggregateVM covers arities 1 through 5

spec/VERSION pinned at 1.0.0. spec/README.md updated to reflect the now-
populated directory.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.2"
```

______________________________________________________________________

## Task 2 — Overview & concepts (00, 01)

Two high-level introduction documents. They set vocabulary for everything that follows.

**Files:**

- Create: `spec/00-overview.md`
- Create: `spec/01-concepts.md`

### Step 2.1: `spec/00-overview.md`

Create the file with this content:

```markdown
# 00 — Overview

VMx is a hierarchical, lifecycle-aware MVVM viewmodel framework. It defines a tree of
viewmodels (components, composites, groups, aggregates), an explicit lifecycle state
machine (`ConstructionStatus`), commands with reactive triggers, and a hot pub/sub
message hub for change notifications. The library is UI-framework-agnostic and ships
in multiple language flavors with semantically equivalent behavior.

## In scope (1.0)

- Hierarchical viewmodel types: `ComponentVM`, `ReadonlyComponentVM`, `CompositeVM`,
  `GroupVM`, `AggregateVM<VM1..VM5>`, `ForwardingComponentVM`, `ForwardingCompositeVM`.
- Lifecycle state machine: `Disposed`, `Destructing`, `Destructed`, `Constructing`,
  `Constructed`, with `Construct ↔ Destruct` reversibility and terminal `Disposed`.
- Commands: `RelayCommand` with predicates and reactive triggers; parameterized
  variant for typed parameters.
- Message hub: hot stream of `IMessage`-derived events, used for property changes and
  lifecycle status changes.
- Fluent immutable builders for every viewmodel and command type.

## Out of scope (1.0)

- UI bindings. VMs expose `INotifyPropertyChanged`-equivalent semantics; the rendering
  layer is the host application's responsibility.
- Virtualization. See ADR-0005.
- Navigation routing, persistence, serialization. These are application concerns, not
  framework concerns.
- A unified, locked-step version across language flavors. Each flavor versions
  independently; the spec version is the shared anchor (see §7 of the design doc).

## Glossary

| Term | Definition |
|---|---|
| **VM** | viewmodel — an instance of one of the VMx types. |
| **model** | the domain object a VM wraps (optional; `Readonly*` and `*Of[M]` variants attach a typed model). |
| **parent** | the composite that owns a VM (a child can have at most one parent). |
| **current** | the child currently selected within a composite (at most one per composite). |
| **predicate** | a `() -> bool` (or `(T) -> bool`) function deciding whether a command can execute. |
| **trigger** | an `IObservable<Unit>` whose emissions cause a command's `CanExecute` to be re-evaluated and `CanExecuteChanged` to be raised. |
| **hub** | the `IMessageHub` instance every VM publishes to and any subscriber can observe. |
| **builder** | an immutable fluent object that accumulates configuration and produces a VM (or command) via `Build()`. |
| **dispatcher** | `IDispatcher` exposes a foreground and a background Rx scheduler; VMs use them to dispatch property-change events and lifecycle work. |
| **foreground** | the Rx scheduler reserved for events that subscribers expect on the UI thread (e.g., `PropertyChanged`, collection notifications). |
| **background** | the Rx scheduler used for VM construction/destruction work that should not block the foreground. |
| **conformance ID** | a stable `XXX-NNN` identifier (e.g., `CVM-001`) in `12-conformance.md` that every language flavor must implement as a passing test. |

## Audience

This spec is the contract that every language implementation must satisfy. The
audience is implementers of language flavors and contributors who change the
semantics of any VM type or service.

End-user documentation (getting-started guides, API reference) is generated per
language and lives under `docs/`.

## Document conventions

- **MUST** / **MUST NOT** / **SHOULD** / **MAY** follow RFC 2119.
- Pseudo-signatures use generic notation (`ComponentVM<M>`, `IList<VM>`); each
  language flavor renders these in its native syntax.
- Cross-references use `§N` for sections of the same document and the filename
  (`02-lifecycle.md`) for sections of other documents.
```

### Step 2.2: `spec/01-concepts.md`

Create the file with this content:

```markdown
# 01 — Core concepts

This document introduces the VMx mental model. Subsequent sections (`02-lifecycle.md`
onwards) give precise normative definitions; this document is the orientation.

## The viewmodel hierarchy

VMx defines five viewmodel families:

| Family | Role | Children | Typical use |
|---|---|---|---|
| `ComponentVM` | leaf | none | a single addressable VM with state |
| `ReadonlyComponentVM` | leaf, immutable model | none | read-only view of a model |
| `CompositeVM` | container with selection | `IList<VM>` + `Current` | a tab strip, a navigation tree |
| `GroupVM` | container without selection | `IList<VM>` | peers shown side-by-side |
| `AggregateVM<VM1..VM5>` | fixed tuple of heterogeneous children | 1–5 typed slots | a screen composed of distinct sub-VMs |
| `ForwardingComponentVM` / `ForwardingCompositeVM` | decorator | wraps another VM | proxies, caching, instrumentation |

Every VM is also a `ComponentVM` (inheritance / protocol composition per language). A
composite's children are themselves VMs and may be composites, components, etc.

### Modeled and readonly variants

Components and composites have two variants:

- **modeled** — the VM holds a `Model` of type `M`. The model can be replaced via
  `vm.Model = m'` (this is a "set" operation, fires `PropertyChangedMessage`).
- **readonly** — the VM is constructed with a model and the model is final. No setter
  is exposed.

### `Current` selection contract

Each `CompositeVM<VM>` has an optional `Current` child. The contract:

- At most one child is `Current` at any time.
- Setting `Current = c` requires `c ∈ children` (otherwise the operation MUST raise).
- Setting `Current = None` is legal at any time.
- The `Current` setter MAY dispatch asynchronously if the builder enabled
  `AsyncSelection(true)`.
- Child VMs observe their selection state via their `IsCurrent` property (raised
  through `PropertyChangedMessage`).

`GroupVM<VM>` has no `Current`. Children are peers.

### `IComponentVM` baseline

Every viewmodel exposes:

- `Name : string` — immutable post-construction; an identifier for the VM.
- `Hint : string` — immutable post-construction; a human-readable hint.
- `Type : ViewModelType` — enum (`Component`, `ReadOnlyComponent`, `Aggregate`,
  `Group`, `Composite`); immutable.
- `IsCurrent : bool` — derived from parent's `Current` reference. Raised through
  property-change notification.
- `IsConstructed : bool` — equals `Status == Constructed`. Raised when `Status`
  changes.
- `Status : ConstructionStatus` — the lifecycle state. See `02-lifecycle.md`.
- The lifecycle commands: `SelectCommand`, `DeselectCommand`, `SelectNextCommand`,
  `SelectPreviousCommand`, `ReconstructCommand`. Each is an `ICommand`-equivalent
  with appropriate predicates.

## Dependency philosophy

Every VM receives two cross-cutting services:

- `IMessageHub` — the pub/sub hub for `IMessage` events.
- `IDispatcher` — exposes `Foreground` and `Background` Rx schedulers.

These are injected via constructor (and via the builder's `Services(hub, dispatcher)`
call for fluent users). VMx does NOT register a global locator. See ADR-0001 and
ADR-0003 for the rationale.

The `IMessageHub` MAY be shared across many VMs or scoped to a sub-tree; that is
the host application's choice. The conformance tests verify that VMs publish to the
hub they were given (`HUB-001`).

## Concurrency philosophy

VMx is **thread-aware but not thread-bound**:

- It does not own a UI thread.
- It uses Rx schedulers (`IDispatcher.Foreground`, `IDispatcher.Background`) to
  dispatch work.
- Subscribers that need to observe events on a specific thread (e.g., a UI thread)
  must inject an `IDispatcher` whose `Foreground` scheduler dispatches there.

The default `IDispatcher` in each language uses the language's standard "main
loop" scheduler for foreground (`SynchronizationContextScheduler` in .NET,
`AsyncIOScheduler(loop)` in Python) and a thread/task pool scheduler for
background.

See `11-threading.md` for the full contract.

## What this spec is not

This spec does not specify:

- The wire format of messages (no serialization).
- The lifetime of `IMessageHub` (the host decides).
- Whether multiple `IMessageHub` instances may coexist (they MAY).
- UI-framework specifics like XAML binding behaviors, accessibility, or rendering.
- The exact Rx version each flavor uses (each flavor's `README.md` documents that).
```

### Step 2.3: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/00-overview.md spec/01-concepts.md
git add spec/00-overview.md spec/01-concepts.md
git commit -m "docs(spec): add 00-overview and 01-concepts

Establishes vocabulary, scope (in/out for v1.0), and the high-level mental
model of the VM hierarchy, selection, modeled variants, dependency
philosophy (DI), and concurrency philosophy (Rx schedulers, no UI thread).

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 3 — Lifecycle (02) + transition fixture

`02-lifecycle.md` is the most normatively dense document because the state machine
governs every VM's behavior. The JSON fixture encodes the transition table so it can
be loaded identically by every language's conformance suite.

**Files:**

- Create: `spec/02-lifecycle.md`
- Create: `spec/fixtures/lifecycle-transitions.json`
- Delete: `spec/fixtures/.gitkeep`

### Step 3.1: `spec/fixtures/lifecycle-transitions.json`

Create the file with exactly this content:

```json
{
  "$schema-version": "1.0.0",
  "states": [
    "Disposed",
    "Destructing",
    "Destructed",
    "Constructing",
    "Constructed"
  ],
  "initial_state": "Destructed",
  "terminal_states": ["Disposed"],
  "transitions": [
    { "from": "Destructed", "via": "construct", "to_intermediate": "Constructing", "to_final": "Constructed", "legal": true },
    { "from": "Constructed", "via": "destruct", "to_intermediate": "Destructing", "to_final": "Destructed", "legal": true },
    { "from": "Constructed", "via": "reconstruct", "to_intermediate": "Destructing", "to_final": "Constructed", "legal": true },
    { "from": "Constructed", "via": "dispose", "to_intermediate": null, "to_final": "Disposed", "legal": true },
    { "from": "Destructed", "via": "dispose", "to_intermediate": null, "to_final": "Disposed", "legal": true },
    { "from": "Constructing", "via": "dispose", "to_intermediate": null, "to_final": "Disposed", "legal": true },
    { "from": "Destructing", "via": "dispose", "to_intermediate": null, "to_final": "Disposed", "legal": true },
    { "from": "Disposed", "via": "construct", "to_intermediate": null, "to_final": null, "legal": false },
    { "from": "Disposed", "via": "destruct", "to_intermediate": null, "to_final": null, "legal": false },
    { "from": "Disposed", "via": "reconstruct", "to_intermediate": null, "to_final": null, "legal": false },
    { "from": "Disposed", "via": "dispose", "to_intermediate": null, "to_final": "Disposed", "legal": true },
    { "from": "Constructed", "via": "construct", "to_intermediate": null, "to_final": "Constructed", "legal": true },
    { "from": "Destructed", "via": "destruct", "to_intermediate": null, "to_final": "Destructed", "legal": true },
    { "from": "Constructing", "via": "construct", "to_intermediate": null, "to_final": null, "legal": false },
    { "from": "Destructing", "via": "destruct", "to_intermediate": null, "to_final": null, "legal": false }
  ]
}
```

Notes on the schema:

- `from` is the state before the operation is invoked.
- `via` is the operation name in the spec (`construct`, `destruct`, `reconstruct`, `dispose`).
- `to_intermediate` is the state the VM passes through during the operation
  (e.g., `Constructing`), or `null` if the operation is instantaneous (e.g., dispose
  from a non-construction state) or illegal.
- `to_final` is the state reached on successful completion, or `null` if the operation
  is illegal.
- `legal: false` means the implementation MUST raise `StatusTransitionError` /
  `StatusTransitionException`.
- Re-invoking `construct` from `Constructed` or `destruct` from `Destructed` is a
  no-op (legal, ends in the same state).
- Re-invoking the same operation while it's in progress (`Constructing` × `construct`)
  is illegal — implementations MUST raise. This catches re-entrant misuse.

### Step 3.2: `spec/02-lifecycle.md`

Create the file with this content:

```markdown
# 02 — Lifecycle state machine

Every viewmodel has a `Status` of type `ConstructionStatus`. The state machine is
defined here normatively and encoded in `fixtures/lifecycle-transitions.json` so
every language's conformance tests can load the same table.

## States

```

Disposed     ← terminal; once entered, cannot leave
Destructing  ← transient; during destruct()
Destructed   ← initial state of a freshly built VM
Constructing ← transient; during construct()
Constructed  ← ready-to-use state

```

`IsConstructed` is defined as `Status == Constructed`. This is normative.

## Operations

A VM exposes four lifecycle operations (rendered per language as
`construct/destruct/reconstruct/dispose` or `Construct/Destruct/Reconstruct/Dispose`):

- `construct()` — moves `Destructed → Constructing → Constructed`.
- `destruct()` — moves `Constructed → Destructing → Destructed`.
- `reconstruct()` — equivalent to `destruct()` followed by `construct()`.
- `dispose()` — moves to `Disposed` from any state. Terminal.

Each operation MAY be invoked synchronously or asynchronously. When invoked
asynchronously, the operation completes when the final state is reached. Subscribers
to the message hub observe two `ConstructionStatusChangedMessage` emissions per
non-trivial transition: one for the intermediate state and one for the final state.

### `can_construct` / `can_destruct` / `can_reconstruct` predicates

Each operation has a paired predicate. Predicates are defined as:

- `can_construct()` returns `true` iff `Status ∈ {Destructed, Constructed}`. (Re-
  constructing while already `Constructed` is a no-op.)
- `can_destruct()` returns `true` iff `Status ∈ {Constructed, Destructed}`. (Re-
  destructing while already `Destructed` is a no-op.)
- `can_reconstruct()` returns `true` iff `Status == Constructed`.

Calling an operation when its predicate returns `false` MUST raise
`StatusTransitionError` (Python) / `StatusTransitionException` (C#). The exception's
message MUST include the current state and the attempted operation.

## Invariants

These hold for every VM at every point in its lifetime:

1. `Status` is one of the five `ConstructionStatus` values.
2. `IsConstructed == (Status == Constructed)`.
3. Once `Status` reaches `Disposed`, it never changes again. All operations from
   `Disposed` (except `dispose` itself, which is idempotent) raise.
4. Every `Status` change publishes exactly one `ConstructionStatusChangedMessage`
   on the VM's message hub before the operation returns (synchronous) or before the
   awaiter resumes (asynchronous).
5. A VM in `Constructing` or `Destructing` MUST NOT have its operation re-invoked
   concurrently. Implementations MUST raise on the second invocation.

## Idempotency

- `construct()` from `Constructed` is a no-op. `Status` remains `Constructed`. No
  `ConstructionStatusChangedMessage` is emitted.
- `destruct()` from `Destructed` is a no-op. Same emission behavior.
- `dispose()` from `Disposed` is a no-op. No emission.

## Reconstruct

`reconstruct()` is defined as `destruct()` followed by `construct()`. The two are
executed in order, and the message hub observes the full transition sequence:
`ConstructionStatusChangedMessage(Destructing)`, `(Destructed)`, `(Constructing)`,
`(Constructed)`. See ADR-0002 for the rationale of why this is a first-class
operation rather than letting users compose it themselves.

## Parent–child orchestration

`CompositeVM`, `GroupVM`, and `AggregateVM` compose their children's lifecycles:

- A composite/group/aggregate's `construct()` completes only when every child has
  reached `Constructed`.
- A composite/group/aggregate's `destruct()` completes only when every child has
  reached `Destructed`.
- The children are constructed/destructed in parallel. The parent observes its
  children's `ConstructionStatusChangedMessage` emissions to know when to finalize
  its own state.

Specific conformance IDs for this behavior live in `06-composite-vm.md`,
`07-group-vm.md`, and `08-aggregate-vm.md`.

## Disposal cascade

`dispose()` on a parent disposes every child (synchronously, depth-first). This
ensures no orphaned `IDisposable` resources are left behind.

A disposed VM MAY still receive late-arriving subscriber events from the hub if
those events were already in flight. Subscribers MUST be tolerant of this.

## Reference table

See `fixtures/lifecycle-transitions.json` for the complete legal/illegal transition
matrix. Conformance tests (`LIFE-NNN` in `12-conformance.md`) load that fixture
directly.
```

### Step 3.3: Clean up fixtures placeholder

```bash
cd /Users/kaveh/repos/VMx
git rm spec/fixtures/.gitkeep
```

### Step 3.4: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
python3 -c "import json; json.load(open('spec/fixtures/lifecycle-transitions.json'))" && echo "VALID JSON"
pre-commit run --files spec/02-lifecycle.md spec/fixtures/lifecycle-transitions.json

git add spec/02-lifecycle.md spec/fixtures/lifecycle-transitions.json
git commit -m "docs(spec): add 02-lifecycle and lifecycle-transitions.json fixture

Defines the ConstructionStatus state machine normatively, with the legal
and illegal transition matrix encoded as JSON so every language's
conformance tests can load the same data. Covers: five states, four
operations (construct/destruct/reconstruct/dispose) with their predicates,
six invariants, idempotency rules, parent-child orchestration, and
disposal cascade.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1, §6.3"
```

______________________________________________________________________

## Task 4 — Messages (03) + ordering fixture

**Files:**

- Create: `spec/03-messages.md`
- Create: `spec/fixtures/message-ordering.json`

### Step 4.1: `spec/fixtures/message-ordering.json`

```json
{
  "$schema-version": "1.0.0",
  "scenarios": [
    {
      "id": "single-producer-fifo",
      "description": "One producer sends 3 messages; a single subscriber observes them in send order.",
      "producer_sends": ["A", "B", "C"],
      "expected_observed": ["A", "B", "C"]
    },
    {
      "id": "late-subscribe-no-replay",
      "description": "A subscriber that subscribes after a message is sent does not receive that message.",
      "producer_sends_before_subscribe": ["A"],
      "producer_sends_after_subscribe": ["B", "C"],
      "expected_observed": ["B", "C"]
    },
    {
      "id": "multiple-subscribers-same-message",
      "description": "Each subscriber observes every message sent after it subscribed.",
      "subscriber_count": 3,
      "producer_sends": ["A", "B"],
      "expected_observed_per_subscriber": ["A", "B"]
    },
    {
      "id": "unsubscribe-during-emit",
      "description": "If a subscriber disposes its subscription while a message is being delivered, the dispatch must complete without raising.",
      "producer_sends": ["A", "B"],
      "unsubscribe_after_first": true,
      "expected_observed": ["A"]
    }
  ]
}
```

### Step 4.2: `spec/03-messages.md`

```markdown
# 03 — Messages and the message hub

VMx uses a single hot pub/sub stream — the message hub — to convey property changes,
lifecycle status changes, and any future event types. Subscribers observe via an Rx
`Observable<IMessage>`.

## `IMessage` shape

Every message implements `IMessage` (rendered per language as `Message`):

```

IMessage:
SenderName : string
SenderObject : object

```

Strongly-typed senders are exposed via `IMessage<TSender>`:

```

IMessage<TSender> : IMessage:
Sender : TSender

```

`SenderName` typically equals `Sender.Name`. `SenderObject` is the runtime sender
without compile-time type information (used by polymorphic subscribers).

## Concrete message types

VMx 1.0 defines two concrete messages. Both are immutable.

### `PropertyChangedMessage<TSender>`

Emitted when a property's setter assigns a new value (a value not equal to the
existing one). Carries:

```

PropertyChangedMessage<TSender> : IMessage<TSender>:
PropertyName : string

```

A factory `Create(sender, senderName, propertyName)` exists per language.

### `ConstructionStatusChangedMessage`

Emitted on every legal `Status` transition (see `02-lifecycle.md`). Carries:

```

ConstructionStatusChangedMessage : IMessage:
Status : ConstructionStatus

```

A factory `Create(sender, senderName, status)` exists per language.

## The hub contract

`IMessageHub` exposes:

```

IMessageHub:
Messages : Observable<IMessage>
Send<TMessage : IMessage>(message: TMessage) : void

```

### Hot stream semantics

The hub is a **hot** Rx stream:

- `Send` delivers to every current subscriber synchronously.
- A subscriber added after a `Send` call does NOT observe that message.
- There is no replay buffer.

### Ordering

For a single producer (a single thread calling `Send` in sequence), every subscriber
observes the messages in send order (FIFO). Across producers (concurrent `Send`
calls), the hub MAY interleave but MUST preserve per-producer order: if producer P
sends `A` then `B`, no subscriber observes `B` before `A`.

### Subscriber resilience

If a subscriber's handler raises, the hub MUST swallow the exception (the stream
continues for other subscribers and for future `Send` calls). Raising subscribers
are a contributor concern, not a hub concern.

If a subscriber disposes its subscription during the delivery of a message (e.g.,
the handler calls `subscription.Dispose()`), the in-flight dispatch completes
normally; subsequent messages are not delivered to that subscriber.

### Multiplicity

A host application MAY create as many `IMessageHub` instances as it likes. The
common pattern is one hub per VM tree (per "screen" or "feature"); shared root hubs
across the whole app are also valid.

## Threading

`Send` runs on the calling thread. Subscribers wishing to observe on a specific
thread/scheduler MUST apply `.ObserveOn(scheduler)` themselves. VMx does not impose
a scheduler choice on the hub.

VMs that emit `PropertyChangedMessage` (Status changes, model changes, etc.) MAY
dispatch the emission via `IDispatcher.Foreground` so subscribers can opt into
foreground-thread delivery via `ObserveOn(dispatcher.Foreground)`. See
`11-threading.md` for the full contract.

## Fixture

`fixtures/message-ordering.json` encodes the four scenarios that the `HUB-NNN`
conformance tests load:

- `single-producer-fifo`: 3 messages → 3 observations, same order.
- `late-subscribe-no-replay`: pre-subscribe sends are not observed.
- `multiple-subscribers-same-message`: every subscriber observes every post-subscribe
  message.
- `unsubscribe-during-emit`: a subscriber disposing during delivery does not crash.
```

### Step 4.3: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
python3 -c "import json; json.load(open('spec/fixtures/message-ordering.json'))" && echo "VALID JSON"
pre-commit run --files spec/03-messages.md spec/fixtures/message-ordering.json

git add spec/03-messages.md spec/fixtures/message-ordering.json
git commit -m "docs(spec): add 03-messages and message-ordering.json fixture

Defines IMessage, two concrete messages (PropertyChanged, ConstructionStatusChanged),
the IMessageHub hot-stream contract (Send + Messages Observable), and the four
ordering / late-subscribe / multi-subscriber / unsubscribe-during-emit invariants
in machine-checkable JSON.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 5 — Commands (04) + command truth table

**Files:**

- Create: `spec/04-commands.md`
- Create: `spec/fixtures/command-truthtable.json`

### Step 5.1: `spec/fixtures/command-truthtable.json`

```json
{
  "$schema-version": "1.0.0",
  "cases": [
    { "id": "no-predicate-no-trigger", "predicate": null, "task": "noop", "trigger_emits": false, "can_execute": true, "execute_invokes_task": true, "can_execute_changed_fires": false },
    { "id": "predicate-true",          "predicate": true, "task": "noop", "trigger_emits": false, "can_execute": true, "execute_invokes_task": true, "can_execute_changed_fires": false },
    { "id": "predicate-false",         "predicate": false,"task": "noop", "trigger_emits": false, "can_execute": false,"execute_invokes_task": false,"can_execute_changed_fires": false },
    { "id": "trigger-fires-can-execute-event", "predicate": true, "task": "noop", "trigger_emits": true, "can_execute": true, "execute_invokes_task": true, "can_execute_changed_fires": true },
    { "id": "null-task",               "predicate": true, "task": null,   "trigger_emits": false, "can_execute": true, "execute_invokes_task": false,"can_execute_changed_fires": false }
  ]
}
```

Note: `task: "noop"` means "the configured task is a no-op function"; `task: null` means
"no task configured" (`execute()` is a no-op and MUST NOT raise).

### Step 5.2: `spec/04-commands.md`

```markdown
# 04 — Commands

VMx commands implement an `ICommand`-style interface and use Rx for reactive
re-evaluation of `CanExecute`.

## Command contract

```

ICommand:
CanExecute() : bool
Execute() : void
CanExecuteChanged : event  / Observable<Unit>

```

A parameterized variant accepts a typed parameter:

```

ICommand<T>:
CanExecute(parameter: T) : bool
Execute(parameter: T) : void
CanExecuteChanged : event  / Observable<Unit>

```

## Predicate semantics

A command is built with an optional `predicate` (`() -> bool` or `(T) -> bool`):

- If `predicate` is null/absent, `CanExecute` returns `true` unconditionally.
- If `predicate` is present, `CanExecute` returns its result.
- The predicate MUST NOT raise. If it does, the language flavor MAY treat the result
  as `false` (defensive) but MUST NOT propagate the exception to the caller.

## Task semantics

A command is built with an optional `task` (`() -> void` / `Action` or `(T) -> void`):

- If `task` is null/absent, `Execute` is a no-op (returns immediately, does not raise).
- If `task` is present, `Execute` invokes it.
- The task MUST NOT raise; if it does, the exception propagates to the caller of
  `Execute`. The exception is the application's responsibility, not the command's.

## Triggers

A command MAY be built with one or more `triggers` (`Observable<Unit>`). On each
emission of any trigger, the command:

1. Re-evaluates `CanExecute`.
2. Fires `CanExecuteChanged` (the consumer-facing event/observable).

Triggers do NOT carry data — only the fact that re-evaluation should happen. The
typical pattern: derive a trigger from a property's change stream
(`vm.Status.Where(s => s == Constructed).Select(_ => Unit.Default)`).

## RelayCommand

`RelayCommand` is the concrete `ICommand` implementation, built via a fluent
immutable builder:

```

RelayCommand.Builder()
.Task(() => ...)         // optional
.Predicate(() => ...)    // optional
.Triggers(observable)    // optional, multiple calls allowed
.Build()

```

`RelayCommand<T>` follows the same pattern with parameterized predicate/task.

## Builder semantics

- Setters return a NEW builder instance (immutability).
- `Triggers` is additive: multiple `.Triggers(obs)` calls combine all observables
  into the trigger set.
- `Build()` succeeds even with no task, no predicate, and no triggers (yielding a
  command whose `CanExecute` returns `true` and whose `Execute` is a no-op).

## Fixture

`fixtures/command-truthtable.json` encodes five canonical command configurations that
`CMD-NNN` conformance tests load. Each row encodes: predicate value, task presence,
trigger behavior, expected `CanExecute` return, whether `Execute` invokes the task,
and whether `CanExecuteChanged` fires.
```

### Step 5.3: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
python3 -c "import json; json.load(open('spec/fixtures/command-truthtable.json'))" && echo "VALID JSON"
pre-commit run --files spec/04-commands.md spec/fixtures/command-truthtable.json

git add spec/04-commands.md spec/fixtures/command-truthtable.json
git commit -m "docs(spec): add 04-commands and command-truthtable.json fixture

Defines ICommand / ICommand<T> contract, predicate and task semantics
(null-safe), reactive triggers, the RelayCommand fluent immutable builder,
and a 5-row truth table that conformance tests load to verify the
CMD-NNN behaviors.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 6 — ComponentVM spec (05)

**Files:**

- Create: `spec/05-component-vm.md`

### Step 6.1: Write the file

```markdown
# 05 — ComponentVM

`ComponentVM` is the leaf VM. Use it for any addressable VM that is not itself a
container.

## Variants

| Variant | Has `Model` | `Model` mutable | Type identifier |
|---|---|---|---|
| `ComponentVM` (non-modeled) | no | n/a | `Component` |
| `ComponentVM<M>` (modeled) | yes | yes | `Component` |
| `ReadonlyComponentVM<M>` | yes | no | `ReadOnlyComponent` |

All three variants share the `IComponentVM` baseline (see `01-concepts.md`).

## Members (every variant)

```

ComponentVM:
Name : string                          # immutable post-construction
Hint : string                          # immutable post-construction
Type : ViewModelType                   # immutable, equals "Component" or "ReadOnlyComponent"
IsCurrent : bool                       # parent-derived; raised through PropertyChanged
IsConstructed : bool                   # equals Status == Constructed
Status : ConstructionStatus            # see 02-lifecycle.md

```
# Built-in commands
SelectCommand : ICommand
DeselectCommand : ICommand
SelectNextCommand : ICommand
SelectPreviousCommand : ICommand
ReconstructCommand : ICommand

# Lifecycle operations
can_construct() : bool
construct() : void  /  async
can_destruct() : bool
destruct() : void  /  async
can_reconstruct() : bool
reconstruct() : void  /  async
dispose() : void

# Selection operations
can_select() : bool
select() : void
can_deselect() : bool
deselect() : void
```

```

## Modeled variant additions (`ComponentVM<M>`)

```

ComponentVM<M> : ComponentVM:
Model : M                              # settable; setting fires PropertyChangedMessage("Model")
ModeledHint : string                   # derived; recomputed when Model changes

```

The setter for `Model`:
1. If the new value equals the old (`==` semantics per language), no message is
   emitted and no derived properties update.
2. Otherwise, the field is replaced, `PropertyChangedMessage("Model")` is emitted,
   and if `ModeledHint` is wired (see below), it is recomputed and
   `PropertyChangedMessage("ModeledHint")` is emitted.

### `ModeledHint`

`ModeledHint` is a derived string computed from `Model` via a `model_hinter`
function provided at build time:

```

modeled_hinter : (M) -> string

```

If no `modeled_hinter` is configured, `ModeledHint` returns the empty string.

### `OnModelChanged`

The builder accepts an `on_model_changed` callback (`(M) -> void`). When the model
setter accepts a new value, this callback is invoked AFTER the
`PropertyChangedMessage` is emitted. Use it to wire model-driven side effects.

## Readonly variant (`ReadonlyComponentVM<M>`)

Same surface as `ComponentVM<M>` minus the `Model` setter. The model is provided at
build time and is final. `ModeledHint` remains derived but stable (the model never
changes).

`Type` equals `ReadOnlyComponent`.

## Built-in commands

| Command | Predicate | Task |
|---|---|---|
| `SelectCommand` | `can_select()` | `select()` |
| `DeselectCommand` | `can_deselect()` | `deselect()` |
| `SelectNextCommand` | parent has a "next" child | move parent's `Current` to next sibling |
| `SelectPreviousCommand` | parent has a "previous" child | move parent's `Current` to previous sibling |
| `ReconstructCommand` | `can_reconstruct()` | `reconstruct()` |

All five commands re-evaluate their predicates on every relevant `Status` change of
the VM (via a trigger derived from `Status`).

## Selection predicates

```

can_select() returns true iff:

- Parent is not null
- Parent.Current != this
- Status == Constructed

can_deselect() returns true iff:

- Parent is not null
- Parent.Current == this

```

`select()` calls `parent.SelectComponent(this)`. `deselect()` calls
`parent.DeselectComponent(this)`. The selection contract is defined in
`06-composite-vm.md`.

## Construction

Construction in this variant amounts to publishing the status transitions. There is
no child orchestration (components have no children). Override hooks for user code
exist (`OnConstruct` / `OnDestruct` callbacks at build time) — see `10-builders.md`.

## Conformance

`CVM-001` through `CVM-006` in `12-conformance.md` cover:
- status emission on construct
- modeled `Model` setter PropertyChanged behavior
- readonly variant has no `Model` setter
- `ModeledHint` recomputation
- `Name`/`Hint`/`Type` immutability
- `SelectCommand` predicate behavior
```

### Step 6.2: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/05-component-vm.md
git add spec/05-component-vm.md
git commit -m "docs(spec): add 05-component-vm

Defines ComponentVM, ComponentVM<M>, ReadonlyComponentVM<M>, their shared
member set (Name/Hint/Type/IsCurrent/IsConstructed/Status, five built-in
commands), the modeled setter semantics, ModeledHint derivation, and the
selection predicates. References CVM-001..006 in the conformance catalog.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 7 — CompositeVM spec (06)

**Files:**

- Create: `spec/06-composite-vm.md`

### Step 7.1: Write the file

```markdown
# 06 — CompositeVM

`CompositeVM<VM>` is a container with selection: it holds an ordered list of child
viewmodels and exposes a `Current` slot that designates at most one child as the
selected one.

## Variants

| Variant | Children source | `Current` |
|---|---|---|
| `CompositeVM<VM>` (non-modeled) | builder factory `() -> Iterable<VM>` | yes |
| `CompositeVM<M, VM>` (modeled) | model factory `() -> Iterable<M>` + mapper `M -> VM` | yes |

## Members

```

CompositeVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged:
\# IComponentVM members (see 01-concepts.md and 05-component-vm.md):
Name, Hint, Type=Composite, IsCurrent, IsConstructed, Status,
SelectCommand, DeselectCommand, SelectNextCommand, SelectPreviousCommand,
ReconstructCommand, can_construct/construct/..., can_select/select/...

```
# CompositeVM-specific:
Current : VM?                        # may be null; one child or none

# IList<VM>:
Add(vm: VM) : void
Remove(vm: VM) : bool
Insert(index: int, vm: VM) : void
RemoveAt(index: int) : void
Clear() : void
Count : int
indexer [i] : VM
iterator

# Selection:
select_component(vm: VM) : void
deselect_component(vm: VM) : void
can_select_component(vm: VM) : bool
```

```

## `Current` contract

- `Current` MAY be `null` (no child selected).
- If `Current` is non-null, it MUST be a member of the children collection.
- Setting `Current` to a value not in the children collection MUST raise.
- Setting `Current = null` is always legal (no-op if already null).
- A change to `Current` fires `PropertyChangedMessage("Current")` and updates the
  affected children's `IsCurrent` (raising their `PropertyChangedMessage("IsCurrent")`).
- If the builder enabled `AsyncSelection(true)`, the setter dispatches the work via
  `IDispatcher.Foreground` and returns immediately. The new `Current` is observable
  only after the dispatcher delivers. If `AsyncSelection(false)` (the default), the
  setter is synchronous.

### `select_component(vm)` / `deselect_component(vm)`

- `select_component(vm)` sets `Current = vm` after verifying `can_select_component(vm)`.
  If the predicate is false, the call raises.
- `deselect_component(vm)` sets `Current = null` after verifying `Current == vm`.
  If `Current != vm`, the call raises.
- `can_select_component(vm)` returns `true` iff `vm ∈ children` and `vm.Status == Constructed`.

## Collection change notification

The collection raises `INotifyCollectionChanged.CollectionChanged` events:

- `Add(vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=Count-1)`.
- `Remove(vm)` → `CollectionChanged(action=Remove, oldItems=[vm], oldIndex=where vm was)`.
- `Insert(i, vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=i)`.
- `RemoveAt(i)` → `CollectionChanged(action=Remove, oldItems=[old], oldIndex=i)`.
- `Clear()` → `CollectionChanged(action=Reset)`.

Implementations MAY suppress notifications during bulk operations (the legacy lib
used a `_suppressNotification` flag); if so, a single `Reset` event MUST be raised
at the end.

## Children construction orchestration

`CompositeVM` overrides the base `construct()` and `destruct()` to coordinate
children:

- `construct()` proceeds through `Destructed → Constructing`. It calls `construct()`
  on every child in parallel and listens on the message hub for each child's
  `ConstructionStatusChangedMessage(Constructed)`. Once every child reaches
  `Constructed`, the composite transitions to `Constructed` and emits its own
  status message.
- `destruct()` proceeds through `Constructed → Destructing`. If `Current != null`,
  the composite first sets `Current = null`. It then calls `destruct()` on every
  child in parallel and waits for every child's
  `ConstructionStatusChangedMessage(Destructed)`. Once every child reaches
  `Destructed`, the composite transitions to `Destructed`.

A child added via `Add` AFTER the composite has reached `Constructed` does NOT
automatically `construct()` — the host must invoke it. (This is a v1.0 limitation;
auto-construct-on-add is a future enhancement.)

## Modeled variant `CompositeVM<M, VM>`

Identical to `CompositeVM<VM>` except the children come from a model factory:

- Builder accepts:
  - `children_models : () -> Iterable<M>`
  - `child_model_to_view_model : (M) -> VM`
- On `construct()`, the composite first evaluates `children_models()`, then maps
  each `M` to a `VM`, then orchestrates children construction as above.

The model values themselves are NOT exposed on the composite; the composite is a
container of VMs, not models. Each child VM is responsible for holding its own
model.

## Conformance

`COMP-001` through `COMP-008` in `12-conformance.md` cover:
- collection-change events on add/remove
- `Current` setter behavior (legal/illegal values)
- async selection dispatch
- `select_component` / `deselect_component` predicates
- construction wait-for-all-children
- destruction unsets `Current` before destructing children
- modeled variant maps model factory output to children
- `can_select_component` returns false for non-children
```

### Step 7.2: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/06-composite-vm.md
git add spec/06-composite-vm.md
git commit -m "docs(spec): add 06-composite-vm

Defines CompositeVM<VM> and CompositeVM<M, VM>: the IList<VM> +
INotifyCollectionChanged surface, the Current selection contract,
select_component/deselect_component/can_select_component, async-selection
dispatch via IDispatcher.Foreground, children construction orchestration
(wait for all children to reach Constructed, etc.), and the modeled variant.
References COMP-001..008 in the conformance catalog.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 8 — GroupVM (07) + AggregateVM (08)

These two are tighter than CompositeVM and ship together.

**Files:**

- Create: `spec/07-group-vm.md`
- Create: `spec/08-aggregate-vm.md`

### Step 8.1: `spec/07-group-vm.md`

```markdown
# 07 — GroupVM

`GroupVM<VM>` is a container of peers — children with no selection. It is identical
to `CompositeVM<VM>` minus the `Current` slot and minus the selection-related
members and commands.

## Members

```

GroupVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged:
\# IComponentVM members:
Name, Hint, Type=Group, IsCurrent, IsConstructed, Status,
ReconstructCommand, can_construct/construct/..., can_select/select/...

```
# IList<VM>:
Add, Remove, Insert, RemoveAt, Clear, Count, indexer, iterator
```

```

Differences from `CompositeVM<VM>`:

- No `Current` property.
- No `SelectCommand`, `DeselectCommand`, `SelectNextCommand`, `SelectPreviousCommand`.
- No `select_component`, `deselect_component`, `can_select_component`.

The `GroupVM` itself can still be selected (its `Select/DeselectCommand` come from
its own parent if it has one). It is only the children that are unselectable.

## Children construction orchestration

Identical to `CompositeVM`: `construct()` waits for every child to reach
`Constructed`; `destruct()` waits for every child to reach `Destructed`. Construct
and destruct proceed in parallel across children.

## Builder

The builder accepts:

- `children : () -> Iterable<VM>` (factory, evaluated on `construct()`).

The modeled variant (if needed) follows the same pattern as `CompositeVM<M, VM>`.
In v1.0 only the non-modeled variant ships.

## Conformance

`GRP-001` through `GRP-004` in `12-conformance.md` cover:
- collection-change events on add/remove
- absence of `Current`
- construction waits for all children
- destruction waits for all children
```

### Step 8.2: `spec/08-aggregate-vm.md`

```markdown
# 08 — AggregateVM

`AggregateVM<VM1..VMN>` is a fixed-arity tuple of heterogeneous component VMs. VMx
v1.0 ships arities 1 through 5 (`AggregateVM1` through `AggregateVM5` — see
ADR-0007).

## Members (arity N)

```

AggregateVMN\<VM1..VMN> : IComponentVM:
\# IComponentVM members:
Name, Hint, Type=Aggregate, IsCurrent, IsConstructed, Status,
SelectCommand, DeselectCommand, ReconstructCommand,
can_construct/construct/..., can_select/select/...

```
# Aggregate-specific:
Component1 : VM1
Component2 : VM2   # only on arity ≥ 2
Component3 : VM3   # only on arity ≥ 3
Component4 : VM4   # only on arity ≥ 4
Component5 : VM5   # only on arity ≥ 5
```

```

A child slot is populated by invoking a lazy factory at construct time. The factory
is provided via the builder:

```

AggregateVM3.Builder()
.Name("...").Hint("...")
.Services(hub, dispatcher)
.Component1(() => MyComponentVM1.Build(...))
.Component2(() => MyComponentVM2.Build(...))
.Component3(() => MyComponentVM3.Build(...))
.Build()

```

## Construction

`construct()`:

1. Invokes every component factory in parallel, populating the `ComponentN` slots.
2. Subscribes to each child's `ConstructionStatusChangedMessage` on the hub.
3. Waits for every child to reach `Constructed`.
4. Transitions to `Constructed` and emits its own status message.

On each successful slot population, the aggregate raises
`PropertyChangedMessage("ComponentN")`.

## Destruction

`destruct()`:

1. Invokes `destruct()` on each `ComponentN` slot in parallel.
2. Waits for every child to reach `Destructed`.
3. Transitions to `Destructed`.

## Selection

The aggregate itself can be selected (via its parent's `Current`), but the
individual `ComponentN` slots are not selectable — they are the aggregate's fixed
structure, not navigable peers.

## Arity rationale

ADR-0007 documents why arities 1–5 are the supported range. For more than 5
heterogeneous children, prefer `CompositeVM<VM>` or `GroupVM<VM>` with a
heterogeneous-base-type `VM`, or compose multiple aggregates.

## Conformance

`AGG-001` through `AGG-005` in `12-conformance.md` cover:
- arity-1 component factory invoked on construct
- arity-2 both components reach Constructed in parallel
- arity-5 all five components reach Constructed before parent
- ComponentN property change fires on construct
- destruction waits for all children
```

### Step 8.3: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/07-group-vm.md spec/08-aggregate-vm.md
git add spec/07-group-vm.md spec/08-aggregate-vm.md
git commit -m "docs(spec): add 07-group-vm and 08-aggregate-vm

GroupVM<VM> is CompositeVM minus selection; identical construction
orchestration. AggregateVM<VM1..VMN> is a fixed-arity tuple; v1.0 supports
arities 1-5 per ADR-0007. Both reference their conformance IDs
(GRP-001..004, AGG-001..005).

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 9 — Forwarding (09) + Builders (10) + Threading (11)

Three short documents that round out the spec proper before the conformance catalog.

**Files:**

- Create: `spec/09-forwarding.md`
- Create: `spec/10-builders.md`
- Create: `spec/11-threading.md`

### Step 9.1: `spec/09-forwarding.md`

```markdown
# 09 — Forwarding decorators

VMx ships two forwarding decorators:

- `ForwardingComponentVM<M>` — wraps an `IComponentVM<M>`.
- `ForwardingCompositeVM<VM>` — wraps an `ICompositeVM<VM>`.

Forwarding decorators delegate every method and property of the wrapped VM to the
wrapped instance by default. Subclasses override individual members to customize
behavior. Use cases: lightweight proxies, caching wrappers, instrumentation,
logging.

## `ForwardingComponentVM<M>`

```

abstract ForwardingComponentVM<M> : IComponentVM<M>:
\_wrapped : IComponentVM<M>
Name => \_wrapped.Name
Hint => \_wrapped.Hint
Type => \_wrapped.Type
IsCurrent => \_wrapped.IsCurrent
IsConstructed => \_wrapped.IsConstructed
Status => \_wrapped.Status
Model => \_wrapped.Model
ModeledHint => \_wrapped.ModeledHint
SelectCommand => \_wrapped.SelectCommand
DeselectCommand => \_wrapped.DeselectCommand
SelectNextCommand => \_wrapped.SelectNextCommand
SelectPreviousCommand => \_wrapped.SelectPreviousCommand
ReconstructCommand => \_wrapped.ReconstructCommand
construct() => \_wrapped.construct()
destruct() => \_wrapped.destruct()
reconstruct() => \_wrapped.reconstruct()
dispose() => \_wrapped.dispose()
select() => \_wrapped.select()
deselect() => _wrapped.deselect()
can_*() => _wrapped.can_*()

```

A subclass overrides any subset of these.

## `ForwardingCompositeVM<VM>`

Same pattern, but additionally forwards the `IList<VM>` surface (Add, Remove,
indexer, iterator, Count, …), the `Current` property, and the selection methods.

Override hooks specifically called out in the legacy library:

- `DoGetType()` → override to return a different `ViewModelType`.
- `DoGetCurrent()` → override to alter selection semantics.
- `DoGetName()` → override to compute a name.
- `DoGetHint()` → override to compute a hint.
- `DoGetEnumerator()` → override to alter iteration order.

Subclasses MUST forward `dispose()` to the wrapped instance unless they explicitly
own the wrapped's lifetime.

## Conformance

`FWD-001` through `FWD-003` in `12-conformance.md` cover:
- default delegation of every member to the wrapped VM
- selective override replaces a single behavior
- ForwardingCompositeVM forwards iteration
```

### Step 9.2: `spec/10-builders.md`

```markdown
# 10 — Builders

Every VMx VM and command is constructed via a fluent immutable builder. This document
describes the shared builder semantics; specific builder fields are documented in
each VM's spec file.

## Immutability

A builder is immutable. Every setter returns a NEW builder instance with the updated
field. Example pseudo-code:

```

b1 = ComponentVM<M>.Builder()
b2 = b1.Name("user-vm")
b1 == b2  ?  # false; b2 is a different instance with Name set

```

Implementations MAY use a "frozen dataclass" pattern (Python), a `record`-like value
type (C#), or any structurally-immutable construct.

## Fluent flow

```

ComponentVM<M>.Builder()
.Name("user-vm")
.Hint("Logged-in user")
.Type(ViewModelType.Component)
.Parent(parentComposite)
.Model(currentUser)
.ModeledHinter(u => $"User: {u.DisplayName}")
.OnModelChanged(m => Console.WriteLine($"model changed to {m.Id}"))
.Services(messageHub, dispatcher)
.Build()

```

Order of fluent calls is irrelevant. Repeated calls to the same setter overwrite
the prior value (e.g., calling `.Name("a").Name("b")` results in `Name == "b"`).
The one exception is additive setters like `Triggers` on `RelayCommand` — see
`04-commands.md`.

## Validation

`Build()` MUST validate required fields:

| VM type | Required fields |
|---|---|
| `ComponentVM`, `ReadonlyComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVMN` | `Name`, `Services(IMessageHub, IDispatcher)` |
| `ComponentVM<M>`, `ReadonlyComponentVM<M>`, `CompositeVM<M, VM>` | additionally: a model source (model setter for modeled; `Model(...)` for readonly; `ChildrenModels(...)` for modeled composite) |
| `CompositeVM<VM>`, `GroupVM<VM>` | additionally: `Children(() -> ...)` factory |
| `AggregateVMN` | additionally: every `ComponentI` factory for `I = 1..N` |
| `RelayCommand`, `RelayCommand<T>` | (no required fields; a no-op command is valid) |

If a required field is missing, `Build()` raises a `BuilderValidationError` /
`InvalidOperationException` whose message identifies the missing field.

## Default values

Optional fields have these defaults if not set:

- `Hint` → empty string
- `Type` → derived from the VM class (e.g., `Composite` for `CompositeVM.Builder()`)
- `Parent` → null
- `AsyncSelection` → false (composites only)
- `OnConstruct`, `OnDestruct` → no-op callbacks
- `ModeledHinter` → `(m) -> ""` (modeled variants only)
- `OnModelChanged` → no-op callback (modeled variants only)
- `Predicate` (commands) → returns `true`
- `Task` (commands) → no-op
- `Triggers` (commands) → empty set

## Repeated identical calls

Calling `Build()` twice on the same fully-configured builder MUST produce two VMs
that are functionally equivalent (the SAME `Name`, same `Hint`, same wired services,
etc.) but DISTINCT instances. Builders themselves are reusable.

## Conformance

`BLD-001` through `BLD-004` in `12-conformance.md` cover:
- setter returns a new builder instance
- required fields validated on `Build()`
- repeated identical calls produce equivalent VMs
- field defaults applied when not set
```

### Step 9.3: `spec/11-threading.md`

```markdown
# 11 — Threading and schedulers

VMx is thread-aware but not thread-bound. This document defines the contract every
language flavor must satisfy for thread/scheduler dispatch.

## `IDispatcher`

Every VM holds an `IDispatcher`:

```

IDispatcher:
Foreground : IScheduler   # Rx scheduler for events subscribers expect on the UI thread
Background : IScheduler   # Rx scheduler for VM lifecycle work

```

The `IDispatcher` is provided via constructor / builder. There is no global
dispatcher. A host application typically creates one dispatcher per VM tree (or
shares one across all trees).

## Default dispatchers

Each language flavor ships an `RxDispatcher` whose defaults are:

| Language | Foreground | Background |
|---|---|---|
| C# | `SynchronizationContextScheduler` bound to the current thread's `SynchronizationContext` | `TaskPoolScheduler.Default` |
| Python | `AsyncIOScheduler(loop)` for the current event loop | `ThreadPoolScheduler()` |
| TypeScript (future) | `queueScheduler` (microtask) | `asapScheduler` |

UI integrations (WPF, Avalonia, MAUI, tkinter, PyQt, …) provide their own
foreground scheduler tied to the UI thread.

## Foreground emissions

VMs MUST dispatch the following emissions via `IDispatcher.Foreground`:

- Every `PropertyChangedMessage` they emit.
- Every `INotifyCollectionChanged.CollectionChanged` event (composites and groups).
- The `IsCurrent` property change on every child of a composite whose `Current`
  changed.

Implementations MAY achieve this either by:
- Calling `Send` on the hub from the foreground thread (synchronous dispatch); or
- Calling `Send` on any thread and having the hub's `Messages` observable
  `.ObserveOn(dispatcher.Foreground)` so subscribers get a foreground-dispatched
  delivery. The spec does not prescribe which; only that subscribers can opt in
  via `ObserveOn` and see foreground delivery.

## Background work

VMs MAY perform construction and destruction work on `IDispatcher.Background`. The
builder option `Background(true)` (or `Async(true)` per flavor) enables this:

```

ComponentVM<M>.Builder()
.Background(true)
...
.Build()

```

With background enabled, `construct()` and `destruct()` return immediately and
complete asynchronously. The status transitions are still observable via the
hub; subscribers that need to await completion should subscribe to
`ConstructionStatusChangedMessage` and filter for the terminal state.

With background disabled (the default), `construct()` and `destruct()` run on
the calling thread and complete before returning.

## Conformance

`THR-001` through `THR-004` in `12-conformance.md` cover:
- `PropertyChanged` observed on foreground scheduler
- Background construct dispatches on background scheduler
- `CollectionChanged` observed on foreground scheduler
- Subscriber observes on chosen scheduler via `ObserveOn`
```

### Step 9.4: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/09-forwarding.md spec/10-builders.md spec/11-threading.md
git add spec/09-forwarding.md spec/10-builders.md spec/11-threading.md
git commit -m "docs(spec): add 09-forwarding, 10-builders, 11-threading

Forwarding decorators (ForwardingComponentVM<M>, ForwardingCompositeVM<VM>)
delegate to a wrapped VM and expose override hooks for selective behavior.

Builders are immutable: every setter returns a new builder; Build()
validates required fields; default values documented per field; repeated
identical Build() calls produce equivalent but distinct VMs.

Threading: IDispatcher exposes Foreground and Background Rx schedulers;
PropertyChanged, CollectionChanged, and IsCurrent always observable on
Foreground; Background option enables async construct/destruct.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §5.1"
```

______________________________________________________________________

## Task 10 — The conformance catalog (12)

This is the centerpiece. It enumerates every `XXX-NNN` ID that every language flavor
must implement as a passing test. The plan provides the COMPLETE catalog content
here — no placeholders.

**Files:**

- Create: `spec/12-conformance.md`

### Step 10.1: Write the catalog

Create `/Users/kaveh/repos/VMx/spec/12-conformance.md`:

```markdown
# 12 — Conformance test catalog

This document enumerates every stable conformance test identifier in the form
`XXX-NNN`. Every language flavor MUST implement a passing test for each ID in its
`langs/<lang>/tests/conformance/` directory before it can be marked stable. CI
verifies this via `tools/check-conformance-coverage.py`.

## Identifier prefixes

| Prefix | Area | File |
|---|---|---|
| `LIFE-NNN` | Lifecycle state machine | `02-lifecycle.md` |
| `HUB-NNN` | Message hub | `03-messages.md` |
| `PROP-NNN` | Property change notifications | `03-messages.md` |
| `CMD-NNN` | Commands | `04-commands.md` |
| `CVM-NNN` | ComponentVM (incl. modeled, readonly) | `05-component-vm.md` |
| `COMP-NNN` | CompositeVM | `06-composite-vm.md` |
| `GRP-NNN` | GroupVM | `07-group-vm.md` |
| `AGG-NNN` | AggregateVM | `08-aggregate-vm.md` |
| `FWD-NNN` | Forwarding decorators | `09-forwarding.md` |
| `BLD-NNN` | Builders | `10-builders.md` |
| `THR-NNN` | Threading & schedulers | `11-threading.md` |

## How to read an entry

Each entry follows Given/When/Then. Implementers map Given to test setup, When to
the operation under test, and Then to assertions.

---

## Lifecycle (`LIFE-NNN`)

### LIFE-001 — construct from Destructed transitions through Constructing to Constructed

**Given** a freshly built VM in state `Destructed`
**And** a subscriber to the hub filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes exactly two messages, with `Status` values
`Constructing` then `Constructed` in that order
**And** `vm.IsConstructed` is true after `construct()` returns

### LIFE-002 — destruct from Constructed transitions through Destructing to Destructed

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `destruct()` is called
**Then** the subscriber observes exactly two messages with `Status` values
`Destructing` then `Destructed`
**And** `vm.IsConstructed` is false after `destruct()` returns

### LIFE-003 — reconstruct emits the full Destruct then Construct sequence

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `reconstruct()` is called
**Then** the subscriber observes exactly four messages with `Status` values
`Destructing`, `Destructed`, `Constructing`, `Constructed`, in that order

### LIFE-004 — dispose transitions to Disposed from any state

**Given** a VM in any state ∈ `{Destructed, Constructing, Constructed, Destructing}`
**When** `dispose()` is called
**Then** `vm.Status` equals `Disposed`
**And** a `ConstructionStatusChangedMessage` with `Status = Disposed` is observed
on the hub

### LIFE-005 — construct from Disposed raises

**Given** a VM in state `Disposed`
**When** `construct()` is called
**Then** a `StatusTransitionError` / `StatusTransitionException` is raised
**And** the exception message contains the current state ("Disposed") and the
attempted operation ("construct")

### LIFE-006 — destruct from Disposed raises

**Given** a VM in state `Disposed`
**When** `destruct()` is called
**Then** a `StatusTransitionError` / `StatusTransitionException` is raised

### LIFE-007 — IsConstructed equals Status == Constructed

**Given** a VM in any state
**When** `vm.IsConstructed` is read
**Then** the value equals `(vm.Status == Constructed)`

### LIFE-008 — Concurrent construct while Constructing raises

**Given** a VM whose `construct()` is in progress (state `Constructing`, has not yet
reached `Constructed`)
**When** a second `construct()` is invoked concurrently
**Then** the second call raises `StatusTransitionError` / `StatusTransitionException`

### LIFE-009 — construct from Constructed is idempotent (no-op)

**Given** a VM in state `Constructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes NO new messages
**And** `vm.Status` remains `Constructed`

### LIFE-010 — destruct from Destructed is idempotent (no-op)

**Given** a VM in state `Destructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage`
**When** `destruct()` is called
**Then** the subscriber observes NO new messages
**And** `vm.Status` remains `Destructed`

### LIFE-011 — Lifecycle transition table matches fixture

**Given** the JSON fixture `spec/fixtures/lifecycle-transitions.json`
**When** every row in the fixture is exercised against a fresh VM
**Then** rows with `legal: true` complete with the expected `to_final` state
**And** rows with `legal: false` raise `StatusTransitionError` / `StatusTransitionException`

---

## Message hub (`HUB-NNN`)

### HUB-001 — Send delivers to current subscribers

**Given** an `IMessageHub` with one subscriber to `hub.Messages`
**When** `hub.Send(message)` is called
**Then** the subscriber receives `message` synchronously before `Send` returns

### HUB-002 — Late subscribers do not see prior messages

**Given** an `IMessageHub`
**When** `hub.Send(messageA)` is called
**And** a subscriber subscribes to `hub.Messages`
**And** `hub.Send(messageB)` is called
**Then** the subscriber observes only `messageB`

### HUB-003 — Single-producer FIFO order

**Given** an `IMessageHub` with one subscriber
**When** the producer calls `hub.Send(A)`, `hub.Send(B)`, `hub.Send(C)` from the
same thread in that order
**Then** the subscriber observes `A`, `B`, `C` in that order

### HUB-004 — Subscriber dispose during emit does not crash

**Given** an `IMessageHub` with one subscriber whose handler disposes the
subscription on the first message
**When** `hub.Send(A)` then `hub.Send(B)`
**Then** the subscriber observes only `A`
**And** no exception is raised by the hub

### HUB-005 — Multiple subscribers each observe every post-subscribe message

**Given** an `IMessageHub` with N subscribers (N ≥ 2)
**When** the producer calls `hub.Send(message)` once
**Then** every subscriber observes `message` exactly once

### HUB-006 — Hub matches message-ordering fixture

**Given** the JSON fixture `spec/fixtures/message-ordering.json`
**When** every scenario in the fixture is exercised against a fresh hub
**Then** the observed messages match each scenario's `expected_observed`

---

## Property change (`PROP-NNN`)

### PROP-001 — Setting a property to a different value publishes PropertyChangedMessage

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2` where `m2 != m1`
**Then** the subscriber observes exactly one `PropertyChangedMessage` with
`PropertyName = "Model"` and `Sender = vm`

### PROP-002 — Setting a property to the same value does NOT publish

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m1` (same instance)
**Then** the subscriber observes zero `PropertyChangedMessage` emissions

### PROP-003 — Sender identity equals the VM instance

**Given** a modeled `ComponentVM<M>` named "vm1"
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2`
**Then** the observed message's `Sender` is identical to (referentially equal to)
the `vm` instance

### PROP-004 — PropertyName equals the property's name

**Given** a modeled `ComponentVM<M>` with `Name = "n1"`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2`
**Then** the observed message's `PropertyName` is exactly `"Model"`
**And** the message's `SenderName` is `"n1"`

---

## Commands (`CMD-NNN`)

### CMD-001 — execute invokes the configured task

**Given** a `RelayCommand` built with `.Task(t)` where `t` is a no-op recorder
**When** `command.Execute()` is called
**Then** `t` is invoked exactly once

### CMD-002 — can_execute with no predicate returns true

**Given** a `RelayCommand` built without `.Predicate(...)`
**When** `command.CanExecute()` is called
**Then** it returns `true`

### CMD-003 — can_execute returns the predicate result

**Given** a `RelayCommand` built with `.Predicate(() => false)`
**When** `command.CanExecute()` is called
**Then** it returns `false`

### CMD-004 — Trigger emission fires CanExecuteChanged

**Given** a `RelayCommand` built with a single trigger `Subject<Unit>`
**And** a subscriber to `CanExecuteChanged`
**When** the trigger emits one `Unit`
**Then** the subscriber observes exactly one `CanExecuteChanged` fire

### CMD-005 — Parameterized variant passes parameter

**Given** a `RelayCommand<int>` built with `.Task(p => recorder.Record(p))`
**When** `command.Execute(42)` is called
**Then** the recorder receives the value `42`

### CMD-006 — execute with null task is a no-op

**Given** a `RelayCommand` built without `.Task(...)`
**When** `command.Execute()` is called
**Then** no exception is raised
**And** no observable side effect occurs

### CMD-007 — Command truth-table matches fixture

**Given** the JSON fixture `spec/fixtures/command-truthtable.json`
**When** every row is exercised against a freshly built `RelayCommand`
**Then** the row's expected `can_execute`, `execute_invokes_task`, and
`can_execute_changed_fires` results all hold

---

## ComponentVM (`CVM-NNN`)

### CVM-001 — Construct emits ConstructionStatusChangedMessage(Constructed)

**Given** a `ComponentVM<M>` in `Destructed` state
**And** a subscriber to the hub filtered on `ConstructionStatusChangedMessage`
**When** `construct()` is called
**Then** the subscriber observes at least one message with `Status = Constructing`
**And** then a message with `Status = Constructed`
**And** `vm.IsConstructed` is true after the call

### CVM-002 — Modeled component fires PropertyChanged("Model") on set

**Given** a modeled `ComponentVM<M>` with `Model = m1`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `vm.Model = m2` where `m2 != m1`
**Then** the subscriber observes a message with `PropertyName = "Model"`

### CVM-003 — ReadonlyComponentVM has no Model setter

**Given** a `ReadonlyComponentVM<M>` built with `Model(m1)`
**When** the API surface of the VM is inspected
**Then** there is no public way to set `Model` (no setter property, no method)
**And** `vm.Model == m1`

### CVM-004 — ModeledHint recomputes when Model changes

**Given** a modeled `ComponentVM<M>` built with
  `.ModeledHinter(m => f"hint:{m.Id}")`
**And** `Model = m1` where `m1.Id == 7`
**When** `vm.Model = m2` where `m2.Id == 8`
**Then** `vm.ModeledHint == "hint:8"`
**And** a `PropertyChangedMessage("ModeledHint")` is observed on the hub

### CVM-005 — Name and Hint are immutable post-construction

**Given** a `ComponentVM<M>` built with `Name("orig")` and `Hint("h")`
**When** the API surface is inspected
**Then** there is no public setter for `Name` or `Hint`
**And** `vm.Name == "orig"` and `vm.Hint == "h"` for the VM's lifetime

### CVM-006 — SelectCommand can_execute reflects selection state

**Given** a `ComponentVM<M>` whose parent has `Current = null`
**When** `SelectCommand.CanExecute()` is called and `vm.Status == Constructed`
**Then** it returns `true`
**And** after `vm.Select()`, `SelectCommand.CanExecute()` returns `false`

---

## CompositeVM (`COMP-NNN`)

### COMP-001 — Add raises CollectionChanged(action=Add)

**Given** an empty `CompositeVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `composite.Add(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with
`action == Add`, `newItems == [vm]`, `newIndex == 0`

### COMP-002 — Remove raises CollectionChanged(action=Remove)

**Given** a `CompositeVM<VM>` containing one VM
**When** `composite.Remove(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with
`action == Remove`, `oldItems == [vm]`, `oldIndex == 0`

### COMP-003 — select_component sets Current

**Given** a `CompositeVM<VM>` containing `vm` in `Constructed` state with
`Current == null`
**When** `composite.select_component(vm)` is called
**Then** `composite.Current == vm`
**And** `vm.IsCurrent == true`
**And** a `PropertyChangedMessage("Current")` is observed on the hub
**And** a `PropertyChangedMessage("IsCurrent")` is observed on the hub with
`Sender == vm`

### COMP-004 — Construct waits until all children reach Constructed

**Given** a `CompositeVM<VM>` in `Destructed` state with N children all in
`Destructed`
**When** `composite.construct()` is called
**Then** when it returns (or its awaiter resumes), every child has `Status == Constructed`
**And** the composite has `Status == Constructed`

### COMP-005 — Destruct waits until all children reach Destructed

**Given** a `CompositeVM<VM>` in `Constructed` state with N children all in
`Constructed` and `Current = c0`
**When** `composite.destruct()` is called
**Then** when it returns, `composite.Current == null`
**And** every child has `Status == Destructed`
**And** the composite has `Status == Destructed`

### COMP-006 — Current is None after destruct

**Given** a `CompositeVM<VM>` in `Constructed` with `Current = c0`
**When** `composite.destruct()` is called
**Then** `composite.Current == null` after the call returns

### COMP-007 — Modeled composite maps model factory output to children

**Given** a `CompositeVM<M, VM>` built with `ChildrenModels(() => [m1, m2])` and
`ChildModelToChildViewModel(m => MakeVM(m))`
**When** `composite.construct()` is called
**Then** `composite.Count == 2`
**And** `composite[0].Model == m1` and `composite[1].Model == m2`

### COMP-008 — can_select_component returns false for non-children

**Given** a `CompositeVM<VM>` containing only `vmA`
**And** a foreign `vmB` (not in the composite)
**When** `composite.can_select_component(vmB)` is called
**Then** it returns `false`
**And** `composite.select_component(vmB)` raises

---

## GroupVM (`GRP-NNN`)

### GRP-001 — Add raises CollectionChanged

**Given** an empty `GroupVM<VM>` in `Constructed` state
**And** a subscriber to `CollectionChanged`
**When** `group.Add(vm)` is called
**Then** the subscriber observes a `CollectionChanged` event with `action == Add`

### GRP-002 — Group has no Current

**Given** a `GroupVM<VM>` instance
**When** the API surface is inspected
**Then** there is no `Current` property
**And** there is no `SelectCommand`, `DeselectCommand`, `SelectNextCommand`,
`SelectPreviousCommand`

### GRP-003 — Construct waits until all children reach Constructed

**Given** a `GroupVM<VM>` in `Destructed` state with N children in `Destructed`
**When** `group.construct()` is called
**Then** when it returns, every child has `Status == Constructed`
**And** the group has `Status == Constructed`

### GRP-004 — Destruct waits until all children reach Destructed

**Given** a `GroupVM<VM>` in `Constructed` state with N children in `Constructed`
**When** `group.destruct()` is called
**Then** when it returns, every child has `Status == Destructed`
**And** the group has `Status == Destructed`

---

## AggregateVM (`AGG-NNN`)

### AGG-001 — Arity-1 ComponentN factory invoked on construct

**Given** an `AggregateVM1<VM1>` in `Destructed` built with `.Component1(() => makeVm1())`
**When** `agg.construct()` is called
**Then** `agg.Component1` is populated with the result of `makeVm1()`
**And** `agg.Component1.Status == Constructed`

### AGG-002 — Arity-2 both components reach Constructed in parallel

**Given** an `AggregateVM2<VM1, VM2>` in `Destructed`
**When** `agg.construct()` is called
**Then** when it returns, both `agg.Component1.Status` and `agg.Component2.Status`
equal `Constructed`
**And** the aggregate's `Status == Constructed`

### AGG-003 — Arity-5 all five components reach Constructed before parent

**Given** an `AggregateVM5<VM1..VM5>` in `Destructed`
**And** a subscriber filtered on `ConstructionStatusChangedMessage` where
`Sender == agg`
**When** `agg.construct()` is called
**Then** the message with `Status = Constructed` and `Sender == agg` is observed
ONLY AFTER every `ComponentI.Status` has reached `Constructed`

### AGG-004 — ComponentN property change fires on construct

**Given** an `AggregateVM3<VM1, VM2, VM3>` in `Destructed`
**And** a subscriber filtered on `PropertyChangedMessage`
**When** `agg.construct()` is called
**Then** three `PropertyChangedMessage` events with `PropertyName ∈ {"Component1",
"Component2", "Component3"}` are observed

### AGG-005 — Destruction waits for all children Destructed

**Given** an `AggregateVM2<VM1, VM2>` in `Constructed`
**When** `agg.destruct()` is called
**Then** when it returns, `agg.Component1.Status == Destructed` AND
`agg.Component2.Status == Destructed`
**And** `agg.Status == Destructed`

---

## Forwarding (`FWD-NNN`)

### FWD-001 — ForwardingComponentVM delegates every member to wrapped

**Given** a `ForwardingComponentVM<M>` wrapping `inner` (no override)
**When** each public member of the forwarding VM is read or invoked
**Then** the result equals the value/effect of the same member on `inner`

### FWD-002 — Selective override replaces a single behavior

**Given** a subclass of `ForwardingComponentVM<M>` that overrides `Hint` to return
`"OVERRIDE"`
**And** the wrapped VM has `Hint == "inner-hint"`
**When** the forwarding VM's `Hint` is read
**Then** the result is `"OVERRIDE"`
**And** all other members still delegate to the wrapped VM unchanged

### FWD-003 — ForwardingCompositeVM forwards iteration

**Given** a `ForwardingCompositeVM<VM>` wrapping a composite containing `[vm1, vm2]`
**When** the forwarding composite is iterated
**Then** the iteration yields `vm1, vm2` in order

---

## Builders (`BLD-NNN`)

### BLD-001 — Setter returns a new builder instance

**Given** a freshly created builder `b1`
**When** `b2 = b1.Name("x")` is called
**Then** `b1` and `b2` are different instances (`b1 is not b2` in Python; reference
inequality in C#)
**And** `b1.Name == null` (or default) while `b2.Name == "x"`

### BLD-002 — Required fields validated on Build

**Given** a builder missing one required field (e.g., no `Services` call)
**When** `.Build()` is called
**Then** a `BuilderValidationError` / `InvalidOperationException` is raised
**And** the exception message identifies which field is missing

### BLD-003 — Repeated identical Build calls produce equivalent VMs

**Given** a fully-configured builder `b`
**When** `vmA = b.Build()` and `vmB = b.Build()` are called
**Then** `vmA` and `vmB` are different instances
**And** `vmA.Name == vmB.Name`, `vmA.Hint == vmB.Hint`, `vmA.Type == vmB.Type`,
and (for modeled variants) `vmA.Model == vmB.Model`

### BLD-004 — Field defaults applied when not set

**Given** a builder configured with only the required fields
**When** `.Build()` is called
**Then** `vm.Hint == ""`, `vm.Parent == null`, `vm.Type ==` the type derived from
the VM class

---

## Threading (`THR-NNN`)

### THR-001 — PropertyChanged observed on foreground scheduler

**Given** a modeled `ComponentVM<M>` built with a dispatcher whose `Foreground` is
a `TestScheduler`-equivalent
**And** a subscriber to the hub's `Messages` filtered on `PropertyChangedMessage`
that uses `ObserveOn(dispatcher.Foreground)`
**When** `vm.Model = m2`
**Then** the subscriber's handler is invoked on the foreground scheduler

### THR-002 — Background construct dispatches on background scheduler

**Given** a `ComponentVM<M>` built with `.Background(true)` and a dispatcher whose
`Background` is a `TestScheduler`-equivalent
**When** `construct()` is called
**Then** the construction work is scheduled on `dispatcher.Background`
**And** the test scheduler advancing time advances the construction

### THR-003 — CollectionChanged observed on foreground scheduler

**Given** a `CompositeVM<VM>` built with a foreground `TestScheduler` and a
subscriber to `CollectionChanged` with `ObserveOn(dispatcher.Foreground)`
**When** `composite.Add(vm)` is called
**Then** the subscriber's handler is invoked on the foreground scheduler

### THR-004 — Subscriber observes on chosen scheduler via ObserveOn

**Given** a subscriber to `hub.Messages.ObserveOn(scheduler)` for any scheduler
**When** `hub.Send(message)` is called
**Then** the subscriber's handler is invoked on `scheduler`
```

### Step 10.2: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files spec/12-conformance.md
git add spec/12-conformance.md
git commit -m "docs(spec): add 12-conformance catalog (v1.0.0)

Enumerates ~60 conformance test IDs across 11 categories:
- LIFE-001..011 (lifecycle state machine)
- HUB-001..006 (message hub)
- PROP-001..004 (property change)
- CMD-001..007 (commands)
- CVM-001..006 (ComponentVM)
- COMP-001..008 (CompositeVM)
- GRP-001..004 (GroupVM)
- AGG-001..005 (AggregateVM)
- FWD-001..003 (Forwarding decorators)
- BLD-001..004 (Builders)
- THR-001..004 (Threading)

Each entry is Given/When/Then prose. Three IDs (LIFE-011, HUB-006, CMD-007)
reference the JSON fixtures so the data-driven tests stay in lockstep
across languages.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §6"
```

______________________________________________________________________

## Task 11 — Conformance coverage tool

A Python script that parses `spec/12-conformance.md`, walks the per-language
conformance directories, and reports gaps. Built with TDD — write the tests first.

**Files:**

- Create: `tools/check-conformance-coverage.py`
- Create: `tools/tests/__init__.py` (empty)
- Create: `tools/tests/conftest.py`
- Create: `tools/tests/test_check_conformance_coverage.py`
- Modify: `tools/README.md` (point at the now-existing tool)

The tool runs under the existing Python environment in `langs/python/`. To keep
tooling and library tests separate, we add a new test runner config that
pytest-discovers `tools/tests/` when invoked from the tools directory.

### Step 11.1: Write the failing tests first

Create `/Users/kaveh/repos/VMx/tools/tests/__init__.py` (empty file).

Create `/Users/kaveh/repos/VMx/tools/tests/conftest.py`:

```python
"""Test config for tools/. Adjusts sys.path so the script under test is importable."""

import sys
from pathlib import Path

# Add tools/ to sys.path so we can import check_conformance_coverage as a module.
TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
```

Create `/Users/kaveh/repos/VMx/tools/tests/test_check_conformance_coverage.py`:

```python
"""Unit tests for tools/check-conformance-coverage.py.

The script is imported under the module name `check_conformance_coverage` (the
hyphen in the filename would prevent direct import, so the script also exists
with an underscore alias via a sys.modules shim — see the script itself).
"""

import textwrap
from pathlib import Path

import pytest

import check_conformance_coverage as ccc


def test_parse_catalog_extracts_ids(tmp_path: Path) -> None:
    catalog = tmp_path / "12-conformance.md"
    catalog.write_text(
        textwrap.dedent(
            """\
            # 12 — Conformance test catalog

            ## Lifecycle (`LIFE-NNN`)

            ### LIFE-001 — construct transitions through Constructing
            ...

            ### LIFE-002 — destruct transitions through Destructing
            ...

            ## Commands (`CMD-NNN`)

            ### CMD-001 — execute invokes task
            ...
            """
        ),
        encoding="utf-8",
    )

    ids = ccc.parse_catalog_ids(catalog)

    assert ids == {"LIFE-001", "LIFE-002", "CMD-001"}


def test_parse_catalog_ignores_prefix_table(tmp_path: Path) -> None:
    """The 'Identifier prefixes' table mentions LIFE-NNN as a literal label,
    not as a test ID. Make sure the parser does not pick those up."""
    catalog = tmp_path / "12-conformance.md"
    catalog.write_text(
        textwrap.dedent(
            """\
            ## Identifier prefixes

            | Prefix | Area |
            |---|---|
            | LIFE-NNN | Lifecycle |
            | CMD-NNN | Commands |

            ### LIFE-001 — first real test
            """
        ),
        encoding="utf-8",
    )

    ids = ccc.parse_catalog_ids(catalog)

    assert ids == {"LIFE-001"}


def test_scrape_python_tests_finds_marks(tmp_path: Path) -> None:
    test_file = tmp_path / "test_lifecycle.py"
    test_file.write_text(
        textwrap.dedent(
            """\
            import pytest

            @pytest.mark.conformance("LIFE-001")
            def test_construct_transitions():
                pass

            @pytest.mark.conformance("LIFE-002")
            async def test_destruct_transitions():
                pass

            def test_unrelated_helper():
                pass
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_python_conformance_ids(tmp_path)

    assert found == {"LIFE-001", "LIFE-002"}


def test_scrape_csharp_tests_finds_traits(tmp_path: Path) -> None:
    test_file = tmp_path / "LifecycleTests.cs"
    test_file.write_text(
        textwrap.dedent(
            """\
            using Xunit;

            public class LifecycleTests
            {
                [Fact, Trait("Conformance", "LIFE-001")]
                public void Construct_Transitions() { }

                [Fact]
                [Trait("Conformance", "LIFE-002")]
                public void Destruct_Transitions() { }

                [Fact]
                public void UnrelatedHelper() { }
            }
            """
        ),
        encoding="utf-8",
    )

    found = ccc.scrape_csharp_conformance_ids(tmp_path)

    assert found == {"LIFE-001", "LIFE-002"}


def test_report_gaps_empty_when_complete() -> None:
    catalog = {"LIFE-001", "LIFE-002"}
    language_coverage = {
        "python": {"LIFE-001", "LIFE-002"},
        "csharp": {"LIFE-001", "LIFE-002"},
    }

    gaps = ccc.compute_gaps(catalog, language_coverage)

    assert gaps == {}


def test_report_gaps_lists_missing_ids_per_language() -> None:
    catalog = {"LIFE-001", "LIFE-002", "CMD-001"}
    language_coverage = {
        "python": {"LIFE-001"},
        "csharp": {"LIFE-001", "LIFE-002", "CMD-001"},
    }

    gaps = ccc.compute_gaps(catalog, language_coverage)

    assert gaps == {"python": {"LIFE-002", "CMD-001"}}


def test_main_returns_zero_when_no_active_languages(tmp_path: Path) -> None:
    """If a langs/<lang>/tests/conformance/ directory is empty (no tests at all
    for a flavor), the tool reports it but does not fail. The active-language
    check is opt-in via the --require flag."""
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### LIFE-001 — sample\n", encoding="utf-8")

    (tmp_path / "langs" / "python" / "tests" / "conformance").mkdir(parents=True)
    (tmp_path / "langs" / "csharp" / "tests" / "VMx.Conformance.Tests").mkdir(parents=True)

    rc = ccc.main(["--repo-root", str(tmp_path)])

    assert rc == 0


def test_main_returns_nonzero_when_required_lang_has_gaps(tmp_path: Path) -> None:
    catalog = tmp_path / "spec" / "12-conformance.md"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("### LIFE-001 — sample\n### LIFE-002 — sample\n", encoding="utf-8")

    py_dir = tmp_path / "langs" / "python" / "tests" / "conformance"
    py_dir.mkdir(parents=True)
    (py_dir / "test_x.py").write_text(
        '@pytest.mark.conformance("LIFE-001")\ndef test_one(): pass\n',
        encoding="utf-8",
    )

    rc = ccc.main(["--repo-root", str(tmp_path), "--require", "python"])

    assert rc == 1
```

### Step 11.2: Run the tests to confirm they fail

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run pytest tools/tests/ -v 2>&1 | head -20
```

Expected: every test fails with `ModuleNotFoundError: No module named 'check_conformance_coverage'`. This is the failing baseline.

### Step 11.3: Implement the tool

Create `/Users/kaveh/repos/VMx/tools/check-conformance-coverage.py`:

```python
#!/usr/bin/env python3
"""Cross-language conformance coverage check.

Parses spec/12-conformance.md for every `XXX-NNN` conformance ID, then walks
langs/<lang>/tests/conformance/ for each active language and verifies every ID has
a matching test. Reports gaps to stdout and returns a non-zero exit code if any
language passed via --require has gaps.

Usage:
    python3 tools/check-conformance-coverage.py [--repo-root PATH] [--require LANG ...]

Examples:
    # Default: parse and report, never fail
    python3 tools/check-conformance-coverage.py

    # Require python and csharp to have full coverage (CI mode)
    python3 tools/check-conformance-coverage.py --require python --require csharp
"""

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

# Make the script importable from tests under both filename forms.
sys.modules.setdefault("check_conformance_coverage", sys.modules[__name__])


# ─── parsing ──────────────────────────────────────────────────────────

_ID_PATTERN = re.compile(r"\b([A-Z]{3,5})-(\d{3})\b")
_HEADING_PREFIX = "### "


def parse_catalog_ids(catalog_path: Path) -> set[str]:
    """Return the set of XXX-NNN IDs declared as ### test headings in the catalog.

    We deliberately limit parsing to lines that start with `### ` so that
    references inside body prose (and the "Identifier prefixes" table) are
    ignored. The catalog's convention is one ### heading per test.
    """
    ids: set[str] = set()
    for raw_line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.startswith(_HEADING_PREFIX):
            continue
        for match in _ID_PATTERN.finditer(raw_line):
            ids.add(f"{match.group(1)}-{match.group(2)}")
    return ids


_PY_MARK_PATTERN = re.compile(r'@pytest\.mark\.conformance\(["\']([A-Z]{3,5}-\d{3})["\']\)')
_CS_TRAIT_PATTERN = re.compile(r'Trait\(\s*"Conformance"\s*,\s*"([A-Z]{3,5}-\d{3})"\s*\)')


def scrape_python_conformance_ids(directory: Path) -> set[str]:
    ids: set[str] = set()
    for path in directory.rglob("*.py"):
        for match in _PY_MARK_PATTERN.finditer(path.read_text(encoding="utf-8")):
            ids.add(match.group(1))
    return ids


def scrape_csharp_conformance_ids(directory: Path) -> set[str]:
    ids: set[str] = set()
    for path in directory.rglob("*.cs"):
        for match in _CS_TRAIT_PATTERN.finditer(path.read_text(encoding="utf-8")):
            ids.add(match.group(1))
    return ids


# ─── coverage math ────────────────────────────────────────────────────

def compute_gaps(catalog: set[str], coverage: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return {language: missing_ids} for every language with a non-empty gap."""
    return {
        lang: missing
        for lang, found in coverage.items()
        if (missing := catalog - found)
    }


# ─── language registry ────────────────────────────────────────────────

_SCRAPERS: dict[str, tuple[str, callable]] = {
    "python":  ("langs/python/tests/conformance",        scrape_python_conformance_ids),
    "csharp":  ("langs/csharp/tests/VMx.Conformance.Tests", scrape_csharp_conformance_ids),
}


def collect_coverage(repo_root: Path) -> dict[str, set[str]]:
    """Walk every known language's conformance test directory and report IDs found.

    Languages whose conformance directory does not exist are skipped silently
    (the directory is a Phase 1+ concern; absence simply means "not yet
    implementing conformance").
    """
    coverage: dict[str, set[str]] = {}
    for lang, (rel_dir, scraper) in _SCRAPERS.items():
        directory = repo_root / rel_dir
        if not directory.is_dir():
            continue
        coverage[lang] = scraper(directory)
    return coverage


# ─── reporting ────────────────────────────────────────────────────────

def render_report(catalog: set[str], coverage: dict[str, set[str]], gaps: dict[str, set[str]]) -> str:
    lines: list[str] = []
    lines.append(f"Conformance catalog: {len(catalog)} IDs")
    if not coverage:
        lines.append("No language conformance directories found.")
        return "\n".join(lines)
    for lang in sorted(coverage):
        found = coverage[lang]
        missing = gaps.get(lang, set())
        lines.append(f"  {lang}: {len(found)}/{len(catalog)} covered")
        if missing:
            lines.append(f"    MISSING ({len(missing)}): " + ", ".join(sorted(missing)))
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: the parent of this script).",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        choices=list(_SCRAPERS.keys()),
        help="Language(s) that MUST have full conformance coverage. May be passed multiple times.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root).resolve()
    catalog_path = repo_root / "spec" / "12-conformance.md"
    if not catalog_path.is_file():
        print(f"ERROR: catalog not found at {catalog_path}", file=sys.stderr)
        return 2

    catalog = parse_catalog_ids(catalog_path)
    coverage = collect_coverage(repo_root)
    gaps = compute_gaps(catalog, coverage)
    print(render_report(catalog, coverage, gaps))

    required_gaps = {lang: missing for lang, missing in gaps.items() if lang in args.require}
    if required_gaps:
        print(file=sys.stderr)
        print(f"FAIL: required languages have conformance gaps: {sorted(required_gaps)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
cd /Users/kaveh/repos/VMx
chmod +x tools/check-conformance-coverage.py
```

### Step 11.4: Run the tests, confirm they pass

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run pytest tools/tests/ -v
```

Expected: all 8 tests pass.

### Step 11.5: Run the tool against the real repo to sanity-check

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run python tools/check-conformance-coverage.py
```

Expected output (the exact ID count will reflect what's in `12-conformance.md`):

```
Conformance catalog: 62 IDs
No language conformance directories found.
```

(Or per-language `0/62 covered` lines if the conformance directories exist but are empty. Both are acceptable Phase 1 states.)

### Step 11.6: Update `tools/README.md`

Open `/Users/kaveh/repos/VMx/tools/README.md`. Replace the entire content with:

````markdown
# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

## Current

- `check-conformance-coverage.py` — parses `spec/12-conformance.md` for the catalog
  of `XXX-NNN` conformance IDs and walks each active language's
  `tests/conformance/` directory for matching tests. Reports gaps to stdout and
  exits non-zero if any language passed via `--require` has gaps. Used by the
  `conformance` CI workflow.

  ```bash
  # report-only
  python3 tools/check-conformance-coverage.py

  # CI mode — require python and csharp to be at 100% coverage
  python3 tools/check-conformance-coverage.py --require python --require csharp
````

Unit tests live in `tools/tests/`. Run with:

```bash
uv --project langs/python run pytest tools/tests/
```

## Planned

- `build-compatibility-matrix.py` — regenerates `compatibility-matrix.md` from the
  spec version (`spec/VERSION`) and each language's declared `MinSpecVersion`. To
  be added when the first language flavor releases.
- `spec-to-docs.py` — renders `spec/*.md` into `docs/concepts/` for the docs site.
  To be added when the docs site is wired up (Phase 2k/3j).

````

### Step 11.7: Commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files tools/check-conformance-coverage.py tools/tests/__init__.py tools/tests/conftest.py tools/tests/test_check_conformance_coverage.py tools/README.md

git add tools/check-conformance-coverage.py tools/tests/ tools/README.md
git commit -m "feat(tools): add check-conformance-coverage tool with tests

Parses spec/12-conformance.md for stable XXX-NNN identifiers and walks each
active language's tests/conformance/ directory to verify coverage. Exits
non-zero if any language passed via --require has gaps (CI mode).

Scrapers ship for the two current language flavors:
- python: @pytest.mark.conformance(\"XXX-NNN\")
- csharp: [Trait(\"Conformance\", \"XXX-NNN\")]

8 unit tests cover catalog parsing (incl. ignoring the prefix table),
per-language scraping, gap computation, and the CLI entrypoint.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §6.4"
````

______________________________________________________________________

## Task 12 — Wire conformance.yml + spec-discipline.yml to enforce

The Phase 0 versions of these workflows are no-op skeletons. Now we make them
real.

**Files:**

- Modify: `.github/workflows/conformance.yml`
- Modify: `.github/workflows/spec-discipline.yml`

### Step 12.1: Update `conformance.yml`

Replace the entire content of `/Users/kaveh/repos/VMx/.github/workflows/conformance.yml` with:

```yaml
name: conformance

on:
  push:
    branches: [main]
    paths:
      - "spec/**"
      - "langs/**/tests/conformance/**"
      - "tools/check-conformance-coverage.py"
      - "tools/tests/**"
      - ".github/workflows/conformance.yml"
  pull_request:
    paths:
      - "spec/**"
      - "langs/**/tests/conformance/**"
      - "tools/check-conformance-coverage.py"
      - "tools/tests/**"
      - ".github/workflows/conformance.yml"

jobs:
  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: latest

      - name: Set up Python
        run: uv python install 3.12

      - name: Sync Python dependencies (for pytest)
        run: uv --project langs/python sync --all-extras

      - name: Run tool's own unit tests
        run: uv --project langs/python run pytest tools/tests/ -v

      - name: Report conformance coverage (informational)
        # Phase 1: neither language has shipped 1.0, so we run in report-only mode.
        # Once Phase 2 (C# 1.0) ships, add `--require csharp`. Once Phase 3 (Python
        # 1.0) ships, add `--require python`. The first time a language is at 1.0,
        # CI starts enforcing 100% coverage for it.
        run: uv --project langs/python run python tools/check-conformance-coverage.py
```

### Step 12.2: Update `spec-discipline.yml`

Replace the entire content of `/Users/kaveh/repos/VMx/.github/workflows/spec-discipline.yml` with:

```yaml
name: spec-discipline

on:
  pull_request:
    paths:
      - "spec/**"

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Require ADR for non-trivial spec changes
        run: |
          base_sha="${{ github.event.pull_request.base.sha }}"
          head_sha="${{ github.event.pull_request.head.sha }}"

          # Files under spec/ that don't require a paired ADR (housekeeping):
          # - spec/README.md
          # - spec/VERSION
          # - spec/ADRs/** (the ADRs themselves)
          # - spec/fixtures/** (fixtures may be tweaked alongside spec text)
          changed=$(git diff --name-only "$base_sha" "$head_sha" -- spec/ \
            | grep -v '^spec/README.md$' \
            | grep -v '^spec/VERSION$' \
            | grep -v '^spec/ADRs/' \
            | grep -v '^spec/fixtures/' \
            || true)

          # Newly added ADRs satisfy the rule.
          new_adrs=$(git diff --name-status --diff-filter=A "$base_sha" "$head_sha" -- spec/ADRs/ \
            | awk '{print $2}' || true)

          if [ -n "$changed" ] && [ -z "$new_adrs" ]; then
            echo "::error::Spec text changed but no new ADR was added in spec/ADRs/."
            echo "Changed spec files:"
            echo "$changed"
            echo
            echo "If this change does not warrant an ADR (e.g., it is a typo or pure formatting),"
            echo "the maintainer may add the label 'no-adr-needed' to bypass this check."
            # Allow bypass via PR label.
            if echo "${{ join(github.event.pull_request.labels.*.name, ' ') }}" | grep -q 'no-adr-needed'; then
              echo "Bypassed by 'no-adr-needed' label."
              exit 0
            fi
            exit 1
          fi

          echo "OK: spec changes either include a new ADR or only touch exempted files."

      - name: Require conformance stubs when new IDs are added
        run: |
          base_sha="${{ github.event.pull_request.base.sha }}"
          head_sha="${{ github.event.pull_request.head.sha }}"

          # Detect newly-added XXX-NNN IDs in spec/12-conformance.md (lines starting
          # with "### " that contain the pattern, present in head but not in base).
          new_ids=$(git diff "$base_sha" "$head_sha" -- spec/12-conformance.md \
            | grep -E '^\+### ' \
            | grep -oE '[A-Z]{3,5}-[0-9]{3}' \
            | sort -u || true)

          if [ -z "$new_ids" ]; then
            echo "No new conformance IDs in this PR."
            exit 0
          fi

          echo "New conformance IDs in this PR:"
          echo "$new_ids"

          missing_in=()
          for lang_dir in langs/python/tests/conformance langs/csharp/tests/VMx.Conformance.Tests; do
            if [ ! -d "$lang_dir" ]; then
              continue
            fi
            for id in $new_ids; do
              if ! grep -rq "$id" "$lang_dir"; then
                missing_in+=("$lang_dir:$id")
              fi
            done
          done

          if [ ${#missing_in[@]} -gt 0 ]; then
            echo "::error::Newly-added conformance IDs lack matching test stubs in every active language:"
            for item in "${missing_in[@]}"; do
              echo "  - $item"
            done
            exit 1
          fi

          echo "OK: every new conformance ID has a matching test stub in every active language."
```

### Step 12.3: Verify YAML

```bash
cd /Users/kaveh/repos/VMx
python3 -c "
import yaml
for f in ['.github/workflows/conformance.yml', '.github/workflows/spec-discipline.yml']:
    yaml.safe_load(open(f))
    print(f'VALID: {f}')
"
pre-commit run --files .github/workflows/conformance.yml .github/workflows/spec-discipline.yml
```

### Step 12.4: Commit

```bash
cd /Users/kaveh/repos/VMx
git add .github/workflows/conformance.yml .github/workflows/spec-discipline.yml
git commit -m "ci: wire conformance and spec-discipline workflows for Phase 1

conformance.yml:
- runs the tools/tests/ unit tests (the tool's own tests)
- runs tools/check-conformance-coverage.py in report-only mode in Phase 1
- once a language ships 1.0 (Phase 2 for C#, Phase 3 for Python), the
  workflow gets --require <lang> added so CI enforces 100% coverage for it

spec-discipline.yml:
- fails the build if a PR changes spec text without a matching ADR (with a
  'no-adr-needed' label bypass for typos/formatting)
- fails the build if a PR adds new XXX-NNN conformance IDs without matching
  test stubs in every active language's conformance directory

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §6.5, §10.3"
```

______________________________________________________________________

## Task 13 — Update compatibility-matrix.md

The placeholder is empty (`(none)` row). Now that spec is at 1.0, populate the
first row.

**Files:**

- Modify: `compatibility-matrix.md`

### Step 13.1: Replace the placeholder

Open `/Users/kaveh/repos/VMx/compatibility-matrix.md`. Replace the entire content with:

```markdown
# Spec ↔ language compatibility matrix

This file is regenerated by `tools/build-compatibility-matrix.py` (planned). Until
that tool ships, it is maintained by hand.

| spec  | csharp           | python           | typescript |
| ----- | ---------------- | ---------------- | ---------- |
| 1.0.x | — (Phase 2 WIP)  | — (Phase 3 WIP)  | —          |

A `—` entry indicates no language flavor has yet declared compatibility with that
spec version. Each released language flavor will replace its `—` with its version
range (e.g., `1.0.0–1.2.x`) once it ships against this spec.
```

### Step 13.2: Verify and commit

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files compatibility-matrix.md
git add compatibility-matrix.md
git commit -m "docs: populate compatibility-matrix.md for spec 1.0

First row added: spec 1.0.x. C# and Python columns marked as in-progress
(Phase 2 and Phase 3 respectively); TypeScript marked as not started.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §7"
```

______________________________________________________________________

## Task 14 — Tag spec-v1.0.0 and update CHANGELOG

The spec is complete. Tag the milestone.

**Files:**

- (Tag) `spec-v1.0.0`
- Modify: `langs/csharp/CHANGELOG.md` (optional — note spec dependency)
- Modify: `langs/python/CHANGELOG.md` (optional — note spec dependency)

### Step 14.1: Verify the full local suite one more time

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv sync --all-extras
uv run pytest -v

cd /Users/kaveh/repos/VMx
uv --project langs/python run pytest tools/tests/ -v
uv --project langs/python run python tools/check-conformance-coverage.py

cd /Users/kaveh/repos/VMx/langs/csharp
dotnet test VMx.sln -c Release

cd /Users/kaveh/repos/VMx
pre-commit run --all-files
```

All commands must exit 0. The conformance tool will report `0/<N>` for each
language, which is expected — no language has implemented conformance tests yet.

### Step 14.2: Tag the spec milestone

```bash
cd /Users/kaveh/repos/VMx
git tag -a spec-v1.0.0 -m "spec v1.0.0

Language-neutral VMx specification, version 1.0.0.

Contents:
- 13 spec markdown files (00-overview through 12-conformance)
- 7 ADRs (0001-drop-comscore through 0007-aggregate-vm-arity-1-to-5)
- 3 JSON fixtures (lifecycle-transitions, message-ordering, command-truthtable)
- 62 conformance IDs across 11 categories (LIFE/HUB/PROP/CMD/CVM/COMP/GRP/AGG/FWD/BLD/THR)

Implemented by:
- C# flavor: planned for Phase 2 of the roadmap (csharp-v1.0.0)
- Python flavor: planned for Phase 3 (python-v1.0.0)
- TypeScript flavor: planned post-1.0

See docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md for the
design rationale."
```

### Step 14.3: Update CHANGELOGs to note the spec milestone

Open `/Users/kaveh/repos/VMx/langs/csharp/CHANGELOG.md`. Replace the `## [Unreleased]` section with:

```markdown
## [Unreleased]

### Added
- Initial repo scaffolding.
- Implementing against `spec-v1.0.0`. C# v1.0.0 release planned for Phase 2 of the roadmap.
```

Open `/Users/kaveh/repos/VMx/langs/python/CHANGELOG.md`. Replace the `## [Unreleased]` section with:

```markdown
## [Unreleased]

### Added
- Initial repo scaffolding.
- Implementing against `spec-v1.0.0`. Python v1.0.0 release planned for Phase 3 of the roadmap.
```

### Step 14.4: Commit and push

```bash
cd /Users/kaveh/repos/VMx
pre-commit run --files langs/csharp/CHANGELOG.md langs/python/CHANGELOG.md
git add langs/csharp/CHANGELOG.md langs/python/CHANGELOG.md
git commit -m "docs(changelog): note spec-v1.0.0 as the implementation target

Both per-language CHANGELOGs now name spec-v1.0.0 as the version their
upcoming 1.0 releases will implement against."

# Push the branch
git push -u origin feat/phase-1-spec-v1

# Push the tag
git push origin spec-v1.0.0
```

### Step 14.5: Verify final state

```bash
cd /Users/kaveh/repos/VMx
git log --oneline | head -20
git tag -l | grep spec
git status
```

Expected:

- `git log` shows ~15 new commits on `feat/phase-1-spec-v1`.
- `git tag -l` shows `spec-v1.0.0`.
- `git status` is clean.

______________________________________________________________________

## Phase 1 — completion criteria

Phase 1 is done when **all** of these are true:

1. `spec/VERSION` contains exactly `1.0.0`.
1. All 13 spec markdown files (`00-overview.md` through `12-conformance.md`) exist
   with content matching the outlines in this plan.
1. All 7 ADRs exist (`0001-drop-comscore.md` through `0007-aggregate-vm-arity-1-to-5.md`).
1. All 3 JSON fixtures exist and are valid JSON, with the contents specified in the
   plan.
1. `spec/12-conformance.md` enumerates the 62 conformance IDs listed in this plan
   (LIFE-001..011, HUB-001..006, PROP-001..004, CMD-001..007, CVM-001..006,
   COMP-001..008, GRP-001..004, AGG-001..005, FWD-001..003, BLD-001..004,
   THR-001..004).
1. `tools/check-conformance-coverage.py` exists, is executable, has 8 unit tests
   that pass, and runs cleanly against the real repo.
1. `tools/tests/` directory contains the unit tests passing under `uv run pytest`.
1. `.github/workflows/conformance.yml` runs the unit tests + the coverage tool in
   report-only mode.
1. `.github/workflows/spec-discipline.yml` enforces the ADR-with-spec-change rule
   and the new-conformance-ID-needs-stubs rule.
1. `compatibility-matrix.md` has its first row populated for spec 1.0.x.
1. Per-language `CHANGELOG.md` files note that they implement `spec-v1.0.0`.
1. The branch `feat/phase-1-spec-v1` is pushed and the GitHub Actions for
   `conformance` (and the other workflows triggered by the spec changes) ran
   green.
1. The tag `spec-v1.0.0` is created locally and pushed to origin.

Once these are all true, the spec is the contract. Phase 2 (C# v1.0.0
implementation) can begin against it.

______________________________________________________________________

## Plan self-review notes

- **Spec coverage:** Every section of the design spec (`§5` and `§6`) has a
  corresponding task:
  - §5.1 spec docs (00–12) → Tasks 2–10
  - §5.2 ADRs → Task 1
  - §6.1–6.4 conformance catalog + fixtures + per-language consumption + enforcement
    → Tasks 3, 4, 5, 10, 11, 12
  - §6.5 spec evolution rules → Task 12 (spec-discipline.yml)
  - §7 versioning → Task 13 (compatibility matrix) + Task 14 (tag)
- **Placeholder scan:** Every step shows the actual content the engineer must
  produce. The conformance catalog content (Task 10) is fully spelled out —
  every one of the 62 entries is present with its Given/When/Then. The Python
  tool (Task 11) is shown in full, including all 8 tests. The two YAML
  workflow rewrites are complete.
- **Type consistency:** Names used across the catalog match the spec files
  (`Status`, `ConstructionStatusChangedMessage`, `IsConstructed`,
  `PropertyChangedMessage`, `Current`, `Component1..5`, `IDispatcher`,
  `Foreground`/`Background`, `RelayCommand`, `Trigger`). The conformance IDs
  match between the catalog (Task 10) and the per-domain spec files (Tasks 2–9).
- **Cross-references:** Each spec file references the IDs of its conformance
  tests; the catalog references each spec file at the top of its section. The
  CHANGELOG updates (Task 14) and compatibility-matrix update (Task 13) reference
  `spec-v1.0.0` consistently.
