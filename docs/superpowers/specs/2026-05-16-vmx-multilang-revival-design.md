# VMx — Multi-Language Revival & Restructuring Design

**Status:** Approved (design phase)
**Author:** Kaveh Razavi
**Date:** 2026-05-16
**Repo:** `VMx`
**Supersedes:** the legacy `.NET 4.5` library at `dotnet-tag/src/DotNetTag/VMx/`

---

## 1. Vision

VMx is a hierarchical, lifecycle-aware MVVM viewmodel framework, designed to be:

- **UI-framework-agnostic** — works in any MVVM context (WPF, Avalonia, MAUI, Uno, WinUI in .NET; tkinter, PyQt, Toga in Python; future TS web frameworks) without binding any specific UI library.
- **Reusable across languages** — the same conceptual model is available in C#, Python, and (planned) TypeScript, with idiomatic surfaces per language but semantically equivalent behavior enforced by a shared specification.
- **Modern** — the legacy `.NET 4.5` PCL is replaced by `netstandard2.0`+`net8.0`. External dependencies that no longer make sense (notably `comScore.Services` and `AlphaChiTech.VirtualizingObservableCollection`) are removed. Generics are simplified where it doesn't break the design.

The library covers the viewmodel layer only: component hierarchy, lifecycle, commands, message hub, builders. UI bindings, virtualization, navigation, persistence, and serialization are explicitly out of scope.

---

## 2. Goals & non-goals

### Goals

- Public, open-source library on GitHub.
- Published binaries: NuGet for C#, PyPI for Python, npm for future TypeScript.
- Single monorepo housing all language flavors plus a language-neutral spec.
- Per-language idiomatic API; cross-language semantic parity enforced by a conformance test catalog.
- Independent SemVer per language; shared spec version anchors compatibility (Option A versioning).
- Easy to add additional languages later (Kotlin, Swift, Rust, etc.) via a documented playbook.

### Non-goals

- Mirroring the legacy dotnet VMx API character-for-character. We modernize where the legacy design has aged (comScore dependency, deep generic stacks, virtualization-in-core, service-locator pattern).
- Shipping UI-framework binding helpers in 1.0. (`VMx.Wpf`, `VMx.Avalonia`, etc. are post-1.0 follow-ons.)
- Inventing a custom reactive primitive. We standardize on Rx (System.Reactive / reactivex / rxjs).
- Maintaining a unified version across languages. (See §7.)

---

## 3. Provenance — what we're porting

The legacy library at `/Users/kaveh/repos/dotnet-tag/src/DotNetTag/VMx/` is a `.NET 4.5` Portable Class Library with the following surface (used as the conceptual source for the new design):

- **ViewModel hierarchy:** `IComponentVM`, `IReadonlyComponentVM<M>`, `ICompositeVM<VM>` / `ICompositeVM<M, VM>`, `IGroupVM<VM>`, `IAggregateVM<VM1..VM5>`, `IButtonVM`.
- **Lifecycle state machine:** `ConstructionStatus` enum (`Disposed`, `Destructing`, `Destructed`, `Constructing`, `Constructed`) with reversible Construct↔Destruct and terminal Disposed.
- **Commands:** `CommandBase`, `RelayCommand`, `RelayCommand<T>` with reactive triggers (`IObservable<Unit>`).
- **Messages:** `IMessage<S>`, `IPropertyChangedMessage<S>`, `IConstructionStatusChangedMessage`.
- **Services:** `IMessageHub` (Rx `Subject`-backed pub/sub), `IVMxServiceLocator` (extends `comScore.Services.IServiceLocator`), `IVMxConstants`.
- **Builders:** Fluent immutable builders nested under each VM type (`ComponentVM<M>.Builder()`, etc.).
- **Forwarding decorators:** `ForwardingComponentVM<M>`, `ForwardingCompositeVM<VM>`.

The Python repo currently contains only two stub Protocol files (`messages/contracts/message.py`, `services/contracts/message_hub.py`) and basic OSS hygiene.

---

## 4. Repo layout

```
VMx/                                       (repo root)
├── README.md                              project pitch + flavor matrix + status badges
├── LICENSE                                MIT (existing — kept)
├── .gitignore                             multi-language (.NET, Python, Node, IDEs)
├── .editorconfig                          shared formatting baseline
├── .gitattributes                         line endings, linguist hints
├── .pre-commit-config.yaml                ruff, dotnet format, markdown lint
├── CODEOWNERS, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md
├── compatibility-matrix.md                spec ↔ language version matrix (generated)
│
├── spec/                                  ⭐ source of truth, language-neutral
│   ├── 00-overview.md                     vision, scope, glossary
│   ├── 01-concepts.md                     VM hierarchy, MVVM role, dependency philosophy
│   ├── 02-lifecycle.md                    ConstructionStatus state machine + invariants
│   ├── 03-messages.md                     message hub semantics, ordering, threading
│   ├── 04-commands.md                     command contract, predicates, reactive triggers
│   ├── 05-component-vm.md                 ComponentVM + readonly + modeled variants
│   ├── 06-composite-vm.md                 CompositeVM (selectable children, Current)
│   ├── 07-group-vm.md                     GroupVM
│   ├── 08-aggregate-vm.md                 AggregateVM<VM1..VM5> + arity rationale
│   ├── 09-forwarding.md                   forwarding decorators
│   ├── 10-builders.md                     builder semantics (immutability, fluent flow)
│   ├── 11-threading.md                    foreground/background, scheduler contract
│   ├── 12-conformance.md                  cross-language conformance test catalog
│   ├── VERSION                            current spec version (single line, e.g., 1.0.0)
│   ├── fixtures/
│   │   ├── lifecycle-transitions.json     legal/illegal transition matrix
│   │   ├── message-ordering.json          producer order → expected subscriber order
│   │   └── command-truthtable.json        predicate × trigger × execute results
│   └── ADRs/
│       ├── 0001-drop-comscore.md
│       ├── 0002-rx-as-reactive-primitive.md
│       ├── 0003-constructor-injection.md
│       ├── 0004-langs-folder-layout.md
│       ├── 0005-drop-virtualization-from-core.md
│       ├── 0006-idiomatic-api-per-language.md
│       └── 0007-aggregate-vm-arity-1-to-5.md
│
├── docs/                                  user-facing docs site source
│   ├── index.md
│   ├── getting-started/
│   │   ├── csharp.md
│   │   └── python.md
│   ├── concepts/                          (rendered from spec/)
│   ├── api/                               (per-language API ref, generated)
│   ├── examples/                          (links into /examples)
│   └── mkdocs.yml                         mkdocs-material with language tabs
│
├── examples/                              runnable demos per language
│   ├── csharp/
│   │   ├── HelloVMx/                      minimal console example
│   │   └── WpfTodoApp/                    WPF binding demo
│   └── python/
│       ├── hello_vmx/
│       └── tk_todo_app/                   tkinter binding demo
│
├── langs/                                 ⭐ one folder per language flavor
│   ├── csharp/
│   │   ├── VMx.sln
│   │   ├── Directory.Build.props          shared msbuild props
│   │   ├── Directory.Packages.props       central package versions
│   │   ├── .config/dotnet-tools.json
│   │   ├── CHANGELOG.md
│   │   ├── README.md
│   │   ├── src/
│   │   │   └── VMx/
│   │   │       ├── VMx.csproj             netstandard2.0;net8.0
│   │   │       ├── Lifecycle/
│   │   │       ├── Messages/
│   │   │       ├── Services/
│   │   │       ├── Commands/
│   │   │       ├── Components/
│   │   │       ├── Composites/
│   │   │       ├── Groups/
│   │   │       ├── Aggregates/
│   │   │       ├── Forwarding/
│   │   │       └── Builders/
│   │   └── tests/
│   │       ├── VMx.Tests/                 xUnit unit tests
│   │       └── VMx.Conformance.Tests/     spec conformance suite
│   │
│   └── python/
│       ├── pyproject.toml                 hatchling/uv build, packaging metadata
│       ├── tox.ini                        py3.10/3.11/3.12/3.13 matrix
│       ├── CHANGELOG.md
│       ├── README.md
│       ├── src/
│       │   └── vmx/
│       │       ├── __init__.py            public API re-exports
│       │       ├── __about__.py           __version__, min_spec_version
│       │       ├── py.typed
│       │       ├── lifecycle/
│       │       ├── messages/
│       │       ├── services/
│       │       ├── commands/
│       │       ├── components/
│       │       ├── composites/
│       │       ├── groups/
│       │       ├── aggregates/
│       │       ├── forwarding/
│       │       └── builders/
│       └── tests/
│           ├── unit/
│           └── conformance/
│
├── tools/                                 cross-cutting scripts
│   ├── check-conformance-coverage.py      spec ID ↔ language test coverage
│   ├── build-compatibility-matrix.py      generates compatibility-matrix.md
│   └── spec-to-docs.py                    renders spec/ into docs/concepts/
│
└── .github/
    ├── workflows/
    │   ├── csharp.yml
    │   ├── python.yml
    │   ├── docs.yml
    │   ├── conformance.yml
    │   ├── spec-discipline.yml
    │   ├── release-csharp.yml
    │   └── release-python.yml
    ├── ISSUE_TEMPLATE/
    └── PULL_REQUEST_TEMPLATE.md
```

**Principles baked into the layout**

- Each `langs/<lang>/` is a self-contained project — no cross-language imports, no shared build files. Adding a new language means dropping `langs/<lang>/` in with no impact on siblings.
- `spec/` is the contract. Every implementation satisfies the same semantic model defined here.
- `docs/` is rendered output. Concept pages are sourced from `spec/`; API pages are generated per language and embedded.

---

## 5. Spec contents

### 5.1 Document set

| File | Contents |
| --- | --- |
| `00-overview.md` | One-paragraph vision, in-scope vs. out-of-scope, glossary (VM, model, parent, current, predicate, trigger, hub, builder, dispatcher, foreground/background). |
| `01-concepts.md` | VM hierarchy overview, readonly vs. modeled, `Current` selection contract, property-change notification contract, dependency philosophy (DI, no globals). |
| `02-lifecycle.md` | `ConstructionStatus` states, legal transitions (digraph), invariants (e.g., `IsConstructed ⇔ Status == Constructed`; `Disposed` is irreversible; `Reconstruct = Destruct ∘ Construct`), parent-child orchestration rules. |
| `03-messages.md` | `Message` shape (`sender_name`, `sender_object`, typed `Sender`), concrete message types, hub contract (hot stream, no replay, FIFO per producer thread), threading guarantees. |
| `04-commands.md` | Command contract (`can_execute`, `execute`, `can_execute_changed`), generic parameterized variant, builder fluent flow (`task`, `predicate`, `triggers`, `build`), trigger semantics. |
| `05-component-vm.md` | `ComponentVM` members (`Name`, `Hint`, `Type`, `IsCurrent`, `IsConstructed`, `Status`), built-in commands (`Select`, `Deselect`, `SelectNext`, `SelectPrevious`, `Reconstruct`), lifecycle hooks, modeled and readonly variants. |
| `06-composite-vm.md` | `CompositeVM<VM>` extends `ComponentVM` + `IList<VM>` + collection-change notifications; `Current` selection contract; modeled variant. |
| `07-group-vm.md` | `GroupVM<VM>` — like composite minus selection. |
| `08-aggregate-vm.md` | `AggregateVM<VM1..VM5>` fixed-arity tuple; parallel construct/destruct; arity rationale in ADR-0007. |
| `09-forwarding.md` | `ForwardingComponentVM<M>`, `ForwardingCompositeVM<VM>`; selective override hooks. |
| `10-builders.md` | Builder immutability, fluent flow, validation, factory entrypoints; per-language idiom hints. |
| `11-threading.md` | Two scheduler roles (foreground/background); VMx is thread-aware, not thread-bound; defaults; conformance expectations. |
| `12-conformance.md` | Cross-language conformance test catalog (see §6). |

### 5.2 ADRs (initial set)

1. **0001 — Drop comScore.** External `comScore.Services` dependency removed; replaced with constructor-injected `IMessageHub` / `IDispatcher`.
2. **0002 — Rx as the reactive primitive.** Adopt System.Reactive / reactivex / rxjs over native async/events for the message hub and command triggers.
3. **0003 — Constructor injection.** Drop the service-locator pattern; VMs receive their dependencies via constructor/builder.
4. **0004 — `langs/<lang>/` layout.** Per-language self-contained subprojects under a shared umbrella; alternatives rejected.
5. **0005 — Drop virtualization from core.** `AlphaChiTech.VirtualizingObservableCollection` is removed; virtualization moves to an optional post-1.0 adapter.
6. **0006 — Idiomatic API per language.** Names and shape follow each language's conventions; semantic parity enforced by the spec, not literal mirroring.
7. **0007 — AggregateVM arity 1–5.** Explicit classes for arities 1 through 5 in every language; rationale: compile-time arity in C#, cross-language parity, and "more than 5" should be a composite/group.

---

## 6. Cross-language conformance

### 6.1 Catalog format

Every test case in `spec/12-conformance.md` has a stable identifier and Given/When/Then prose. Identifier prefixes:

| Area | Prefix |
| --- | --- |
| Lifecycle state machine | `LIFE-NNN` |
| Message hub | `HUB-NNN` |
| Property change notifications | `PROP-NNN` |
| Commands | `CMD-NNN` |
| Component VM | `CVM-NNN` |
| Composite VM | `COMP-NNN` |
| Group VM | `GRP-NNN` |
| Aggregate VM | `AGG-NNN` |
| Forwarding | `FWD-NNN` |
| Builders | `BLD-NNN` |
| Threading | `THR-NNN` |

Example entry:

```markdown
### CVM-001 — Constructed status emits ConstructionStatusChangedMessage

Given a ComponentVM in state `Destructed`
And a subscriber to `messageHub.messages` filtering for `ConstructionStatusChangedMessage`
When `construct()` is called
Then the subscriber receives at least one message with `status = Constructing`
And then receives a message with `status = Constructed`
And `vm.isConstructed` is true after `construct()` completes
```

### 6.2 Per-language consumption

- **C#:** `[Fact, Trait("Conformance", "CVM-001")] public async Task CVM_001_…() { … }` under `langs/csharp/tests/VMx.Conformance.Tests/`.
- **Python:** `@pytest.mark.conformance("CVM-001")` `async def test_cvm_001_…(): …` under `langs/python/tests/conformance/`.
- Future languages: same 1:1 ID mapping using the language's idiomatic test framework.

### 6.3 Shared fixtures

JSON files in `spec/fixtures/` hold data that must produce identical outputs across all languages. No shared test runner — each language loads the fixtures natively.

### 6.4 Enforcement

`.github/workflows/conformance.yml` runs `tools/check-conformance-coverage.py`, which:

1. Parses `spec/12-conformance.md` for all `XXX-NNN` IDs.
2. Walks each `langs/<lang>/tests/conformance/` directory for matching IDs using language-specific scrapers.
3. Reports missing IDs per language and fails CI on gaps.

### 6.5 Spec evolution rules

1. Spec changes precede implementation changes. A behavior PR starts with `spec/` + conformance skeletons in every active language.
2. Merged ADRs are immutable except for a top-of-file `Superseded by: ADR-NNNN` marker; replacements are new files.
3. Backward-incompatible spec changes require a major-version bump in every active language flavor (see §7).
4. A new language flavor must pass the entire conformance catalog before being marked stable; it can ship in `0.x` pre-release while gaps remain.

---

## 7. Versioning strategy (Option A — independent per-language SemVer + shared spec version)

| Component | Versioned | Tag format | Notes |
| --- | --- | --- | --- |
| `spec/` | SemVer | `spec-v1.0.0` | Stored in `spec/VERSION`. |
| C# package (`VMx`) | SemVer | `csharp-v1.0.0` | Declares `MinSpecVersion` in package metadata. |
| Python package (`vmx`) | SemVer | `python-v1.0.0` | Declares `min_spec_version` in `__about__.py`. |
| TypeScript package (future `vmx`) | SemVer | `typescript-v1.0.0` | Same pattern. |

**Rules**

1. Each language flavor versions independently; cadence is set by that language's release needs.
2. The spec version is the shared anchor. Every language flavor declares the spec version it implements.
3. Bumping the spec major version requires every active language to bump its major version in turn (tracked via a spec-PR checklist).
4. A compatibility matrix is auto-generated at `compatibility-matrix.md` by `tools/build-compatibility-matrix.py`:

```
spec   csharp   python   typescript
1.0.x  1.0–1.2  1.0–1.1  —
1.1.x  1.3+     1.2+     1.0+
```

5. Language-internal breaking changes (e.g., dropping a deprecated API) are only that language's major bump.

---

## 8. C# library design

### 8.1 Target frameworks & build

- TFMs: `netstandard2.0;net8.0` multi-target.
- `Directory.Build.props` enables: `LangVersion=latest`, `Nullable=enable`, `ImplicitUsings=enable`, `TreatWarningsAsErrors=true`, `EnforceCodeStyleInBuild=true`, `GenerateDocumentationFile=true`, SourceLink + `.snupkg` symbol packages.
- `Directory.Packages.props` centrally pins NuGet versions (`System.Reactive` 6.x, `Microsoft.Bcl.AsyncInterfaces` for netstandard2.0).
- Solution: `langs/csharp/VMx.sln` containing `VMx.csproj`, `VMx.Tests.csproj`, `VMx.Conformance.Tests.csproj`, and (post-1.0) `VMx.Extensions.DependencyInjection.csproj`.

### 8.2 Namespace map

| Folder | Namespace | Public API |
| --- | --- | --- |
| `Lifecycle/` | `VMx.Lifecycle` | `ConstructionStatus`, `StatusTransitionException`, transition validator |
| `Messages/` | `VMx.Messages` | `IMessage`, `IMessage<S>`, `IPropertyChangedMessage<S>`, `IConstructionStatusChangedMessage`, concrete `record` messages |
| `Services/` | `VMx.Services` | `IMessageHub`, `MessageHub`, `IDispatcher`, `RxDispatcher` |
| `Commands/` | `VMx.Commands` | BCL `ICommand`, `RelayCommand`, `RelayCommand<T>`, `ICommandBuilder`, `ICommandBuilder<T>` |
| `Components/` | `VMx.Components` | `IComponentVM`, `IComponentVM<M>`, `IReadonlyComponentVM<M>`, `ComponentVMBase`, sealed `ComponentVM<M>`, `ReadonlyComponentVM<M>` |
| `Composites/` | `VMx.Composites` | `ICompositeVM<VM>`, `ICompositeVM<M, VM>`, base, sealed `CompositeVM<VM>`, `CompositeVM<M, VM>` |
| `Groups/` | `VMx.Groups` | `IGroupVM<VM>`, base, sealed `GroupVM<VM>` |
| `Aggregates/` | `VMx.Aggregates` | `IAggregateVM<…>`, `AggregateVM<…>` for arities 1–5 |
| `Forwarding/` | `VMx.Forwarding` | `ForwardingComponentVM<M>`, `ForwardingCompositeVM<VM>` |
| `Builders/` | `VMx.Builders` | shared builder primitives, validation helpers |

### 8.3 Modernization choices vs. the legacy library

1. **comScore eliminated.** No `IConstants`, no `IServiceLocator`, no `VMxServiceLocatorBase`. Replaced by constructor-injected `IMessageHub` and `IDispatcher`. `AsyncViewModelSelection` becomes a builder option (`.AsyncSelection(true)`).
2. **Generic-parameter simplification.** `ComponentVMBase<SL, L, P, B>` (legacy 4 params) becomes `ComponentVMBase<TSelf, TParent, TBuilder>` (3 params). Modeled variant adds `M`. Sealed concretes expose zero-generic surfaces via nested `Builder()`. The deepest base remains 4-param (load-bearing for fluent-builder return types).
3. **Nullable reference types on.** Optional values are `?`; `Name`/`Hint` non-nullable with empty-string defaults.
4. **`init`-only setters** in builder configuration where the builder is the only legal mutation path.
5. **`record` types** for `PropertyChangedMessage<S>`, `ConstructionStatusChangedMessage`; static `Create` factories preserved.
6. **BCL `ICommand`** retained (`System.Windows.Input.ICommand`) — works in `netstandard2.0` and across WPF/Avalonia/MAUI/Uno without glue.
7. **AggregateVM arities 1–5** implemented as five explicit classes; consider T4 / source generator if duplication becomes painful. Start with hand-written 1 and 2, decide later.
8. **`IDispatcher` abstraction:** `Foreground` and `Background` `IScheduler` properties. Default `RxDispatcher` uses `SynchronizationContextScheduler` (foreground) and `TaskPoolScheduler.Default` (background). Tests inject `Microsoft.Reactive.Testing.TestScheduler` for determinism.
9. **DI integration:** Companion package `VMx.Extensions.DependencyInjection` provides `services.AddVMx(options => options.UseRxDispatcher())`. Optional; core remains DI-container-agnostic.

### 8.4 Sample API surface

```csharp
var vm = ComponentVM<UserModel>.Builder()
    .Name("user-vm")
    .Hint("Logged-in user")
    .Type(ViewModelType.Component)
    .Parent(parentComposite)
    .Model(currentUser)
    .ModeledHinter(u => $"User: {u.DisplayName}")
    .OnModelChanged(m => Console.WriteLine($"model changed to {m.Id}"))
    .Services(messageHub, dispatcher)
    .Build();

await vm.Construct(async: true);
// ...
await vm.Destruct(async: true);
vm.Dispose();
```

```csharp
var canSave = vm.Status.Where(s => s == ConstructionStatus.Constructed).Select(_ => Unit.Default);

var saveCmd = RelayCommand.Builder()
    .Task(() => Save())
    .Predicate(() => vm.IsConstructed)
    .Triggers(canSave)
    .Build();
```

### 8.5 Testing

- `tests/VMx.Tests/` — xUnit + FluentAssertions + `Microsoft.Reactive.Testing.TestScheduler`.
- `tests/VMx.Conformance.Tests/` — implements every `XXX-NNN` from the catalog. Uses `[Trait("Conformance", "XXX-NNN")]` for scraping.
- TDD per `superpowers:test-driven-development` during implementation.

### 8.6 Packaging

- `VMx` (core) → NuGet.
- `VMx.Extensions.DependencyInjection` → NuGet (optional; planned for 1.0 or shortly after).
- Possible future packages: `VMx.Virtualization`, `VMx.Wpf`, `VMx.Avalonia`, `VMx.MAUI`.
- All C# packages share the C# flavor's version number.

---

## 9. Python library design

### 9.1 Build & packaging

- Build backend: `hatchling` (or `uv` — decide in Phase 0 based on what's smoother for the multi-Python-version test matrix; both are acceptable).
- Python versions supported: 3.10 / 3.11 / 3.12 / 3.13.
- Dependencies: `reactivex>=4.0`.
- Dev/test extras: `pytest`, `pytest-asyncio`, `pytest-cov`, `mypy`, `ruff`.
- `py.typed` marker ships in the wheel.
- `tox.ini` runs the full matrix.

### 9.2 Module layout

```
src/vmx/
├── __init__.py                      public API re-exports
├── __about__.py                     __version__, min_spec_version
├── py.typed
├── lifecycle/
│   ├── status.py                    ConstructionStatus enum
│   └── transitions.py               state-machine validation (loads fixtures/lifecycle-transitions.json)
├── messages/
│   ├── protocols.py                 Message, TypedMessage[Sender]   (existing stub goes here)
│   ├── property_changed.py          PropertyChangedMessage[S]
│   └── construction_status.py       ConstructionStatusChangedMessage
├── services/
│   ├── message_hub.py               MessageHub protocol + concrete (existing stub absorbed)
│   └── dispatcher.py                Dispatcher protocol + RxDispatcher
├── commands/
│   ├── protocols.py                 Command, ParameterizedCommand
│   ├── relay_command.py             RelayCommand, RelayCommand[T]
│   └── builders.py                  CommandBuilder, ParameterizedCommandBuilder
├── components/
│   ├── protocols.py
│   ├── base.py
│   ├── component_vm.py              ComponentVM, ComponentVMOf[M]
│   ├── readonly_component_vm.py     ReadonlyComponentVM[M]
│   └── builders.py
├── composites/
├── groups/
├── aggregates/                      AggregateVM1..AggregateVM5 (no TypeVarTuple — explicit arities for parity)
├── forwarding/
└── builders/
    └── base.py
```

### 9.3 Idiomatic translations

| Concept (C#) | Python idiom |
| --- | --- |
| `INotifyPropertyChanged` | `Observable[PropertyChangedMessage]` exposed as `vm.property_changed`; internal mixin publishes via `MessageHub` |
| `ICommand` | `Command` Protocol with `can_execute()`, `execute()`, `can_execute_changed: Observable[bool]` |
| Fluent immutable builder | `@dataclass(frozen=True, slots=True)` builders; each setter returns `dataclasses.replace(self, …)` |
| `Builder()` static factory | top-level factory function: `component_vm()` returns an empty builder |
| `Func<T, R>` / `Action<T>` | `Callable[[T], R]` / `Callable[[T], None]` |
| `IObservable<T>` | `reactivex.Observable[T]` |
| `Task` / async | `asyncio` coroutines; `async def construct(...)` |
| `Dispose` | explicit `dispose()` + `__aenter__`/`__aexit__` for `async with` use |
| Generics | `typing.Generic`, `TypeVar`, `Protocol` |
| `AggregateVM<VM1..VM5>` | `AggregateVM1[VM1]` … `AggregateVM5[VM1,VM2,VM3,VM4,VM5]` — explicit, not `TypeVarTuple` |
| Nullable refs | `T \| None` with mypy `strict` |
| Records | `@dataclass(frozen=True)` |
| Naming | `snake_case` members, `PascalCase` classes, `UPPER_CASE` enum members |

### 9.4 Sample API surface

```python
from vmx.components import component_vm, ViewModelType
from vmx.lifecycle import ConstructionStatus
from vmx.commands import relay_command
import reactivex as rx

vm = (
    component_vm[UserModel]()
    .name("user-vm")
    .hint("Logged-in user")
    .type(ViewModelType.COMPONENT)
    .parent(parent_composite)
    .model(current_user)
    .modeled_hinter(lambda u: f"User: {u.display_name}")
    .on_model_changed(lambda m: print(f"model changed to {m.id}"))
    .services(message_hub, dispatcher)
    .build()
)

await vm.construct(async_=True)
# ...
await vm.destruct(async_=True)
vm.dispose()
```

### 9.5 Dispatcher / threading

```python
class Dispatcher(Protocol):
    @property
    def foreground(self) -> rx.scheduler.SchedulerBase: ...
    @property
    def background(self) -> rx.scheduler.SchedulerBase: ...
```

Default `RxDispatcher`: `reactivex.scheduler.eventloop.AsyncIOScheduler(loop)` for foreground, `reactivex.scheduler.ThreadPoolScheduler()` for background. UI integrations supply their own foreground scheduler.

### 9.6 Lifecycle enum

```python
class ConstructionStatus(enum.IntEnum):
    DISPOSED = 0
    DESTRUCTING = 1
    DESTRUCTED = 2
    CONSTRUCTING = 3
    CONSTRUCTED = 4
```

Same transition table as C#, loaded from `spec/fixtures/lifecycle-transitions.json`. Both languages raise an equivalent `StatusTransitionError` / `StatusTransitionException` on illegal transitions.

### 9.7 Testing

- `tests/unit/` — pytest, `pytest-asyncio`, `pytest-cov`. Marble tests via `reactivex.testing`.
- `tests/conformance/` — implements every `XXX-NNN` from the catalog with `@pytest.mark.conformance("XXX-NNN")`.
- `tox.ini` runs unit + conformance across the Python version matrix.

### 9.8 Treatment of existing Python stubs

- `messages/contracts/message.py` → moves verbatim (modulo path) to `langs/python/src/vmx/messages/protocols.py`.
- `services/contracts/message_hub.py` → moves to `langs/python/src/vmx/services/message_hub.py`; the `Protocol` survives; the concrete `MessageHub` class is added alongside it. Import switches from `rx.core.observable.observable.Observable` → `reactivex.Observable` (rx 3 → reactivex 4).
- Legacy top-level `messages/` and `services/` folders are deleted.

---

## 10. Tooling, CI/CD, release flow

### 10.1 Branch & PR model

- `main` is always releasable. Feature branches → PR → squash-merge.
- Branch protection on `main`: require all status checks (csharp, python, docs, conformance, spec-discipline) + 1 approval. No direct pushes.
- Spec changes require an ADR; enforced by `spec-discipline.yml`.

### 10.2 Per-language CI

- `csharp.yml`: matrix `ubuntu`/`windows`/`macos` × TFMs; `dotnet restore` → `dotnet format --verify-no-changes` → `dotnet build -c Release` → `dotnet test --collect:"XPlat Code Coverage"` → upload to Codecov.
- `python.yml`: matrix Python 3.10/3.11/3.12/3.13 × `ubuntu`/`windows`/`macos`; `uv sync` (or `hatch env create`) → `ruff check` → `ruff format --check` → `mypy --strict src/vmx` → `pytest --cov=vmx --cov-report=xml` → upload to Codecov.

### 10.3 Cross-cutting CI

- `conformance.yml`: runs `tools/check-conformance-coverage.py`; fails on any missing `XXX-NNN` ID; re-runs each language's conformance suite and emits a comparison report.
- `docs.yml`: builds mkdocs-material site from `docs/` + rendered `spec/` + per-language API ref (DocFX for C#, `mkdocstrings` for Python). Deploys to GitHub Pages on `main`.
- `spec-discipline.yml`: if `spec/**` changes without `spec/ADRs/**` added → fail with comment. If `spec/12-conformance.md` adds new IDs → require stub tests in every active language.

### 10.4 Release workflows

- `release-csharp.yml`: triggered by tags matching `csharp-v*`. `dotnet pack -c Release -p:Version=${TAG#csharp-v}` → `dotnet nuget push` via OIDC trusted publishing → GitHub Release with auto-generated notes scoped to `langs/csharp/**`.
- `release-python.yml`: triggered by tags matching `python-v*`. `uv build` → publishes to PyPI via OIDC trusted publishing → GitHub Release scoped to `langs/python/**`.

### 10.5 Local developer tooling

- `.editorconfig` at repo root — shared indentation/EOL/charset.
- `.pre-commit-config.yaml` hooks: `ruff`+`ruff-format` (Python paths), `dotnet format --include` (C# paths), markdown lint (`spec/**`, `docs/**`), trailing-whitespace/EOF fixers.
- `CONTRIBUTING.md` covers both flavors: clone, install pre-commit, run tests, run conformance, render docs locally.

### 10.6 Dependency management

- C#: `Directory.Packages.props` central version pinning.
- Python: `pyproject.toml` loose constraints + committed `uv.lock` (or equivalent) for reproducibility.
- Dependabot enabled for `nuget`, `pip`/`uv`, `github-actions` ecosystems. Auto-merge dev-dep patch bumps when CI passes; manual review otherwise.

### 10.7 Repo metadata files

- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md` (vuln mailbox + GitHub Security Advisories).
- `CHANGELOG.md` per language (`langs/csharp/CHANGELOG.md`, `langs/python/CHANGELOG.md`) in Keep a Changelog format.
- `.github/ISSUE_TEMPLATE/` — `csharp.yml`, `python.yml`, spec-feature request, ADR-proposal.
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist (tests added, spec updated, conformance covered, ADR if applicable).

### 10.8 Docs site stack

- `mkdocs-material` umbrella site.
- Concept pages rendered from `spec/` via `tools/spec-to-docs.py`.
- C# API ref via DocFX; Python API ref via `mkdocstrings`. Both embedded under `docs/api/<lang>/`.
- Deployed to GitHub Pages.

---

## 11. Migration of the existing repo

| Path | Disposition |
| --- | --- |
| `LICENSE` | Stays. Repo-wide. |
| `README.md` (one line) | Rewritten with flavor matrix, links, badges. |
| `.gitignore` | Rewritten as multi-language. |
| `.mypy_cache/`, `.DS_Store` (all) | Deleted + globally ignored. |
| `messages/contracts/message.py` | Moves to `langs/python/src/vmx/messages/protocols.py`. |
| `services/contracts/message_hub.py` | Moves to `langs/python/src/vmx/services/message_hub.py`. |
| `messages/`, `services/` (top-level) | Deleted after content has moved. |
| New top-level dirs | `spec/`, `docs/`, `examples/`, `langs/`, `tools/`, `.github/`. |
| New top-level files | `README.md`, `LICENSE` (kept), `.gitignore` (new), `.gitattributes`, `.editorconfig`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.pre-commit-config.yaml`, `compatibility-matrix.md` (generated). |

The migration is one commit ("everything moves"); subsequent work is additive.

---

## 12. Phased roadmap

### Phase 0 — Repo scaffolding (~a few days)

- Create top-level layout.
- Move/delete legacy Python stubs per the migration table.
- Add repo hygiene files and CI skeleton workflows.
- Skeleton `langs/csharp/VMx.sln` + `Directory.Build.props` + `Directory.Packages.props`; `csharp.yml` builds the empty solution.
- Skeleton `langs/python/pyproject.toml` + empty `src/vmx/__init__.py` + `py.typed`; `python.yml` runs ruff/mypy/pytest on the empty package.
- Repo README rewritten.

**Milestone:** Empty repo with green CI, ready for content.

### Phase 1 — Spec v1.0.0 (~1–2 weeks)

- Write `spec/00-overview.md` through `spec/12-conformance.md`.
- Author ADRs 0001–0007.
- Author `spec/fixtures/*.json`.
- Implement `tools/check-conformance-coverage.py` (no language scrapers yet).
- Tag `spec-v1.0.0`.

**Milestone:** Spec v1.0 tagged. Contract exists.

### Phase 2 — C# v1.0.0 (~3–5 weeks)

Sub-steps (each is its own PR; TDD with conformance tests written before implementation):

- 2a — `Lifecycle` (`ConstructionStatus`, `StatusTransitionException`, transition validator using `lifecycle-transitions.json`).
- 2b — `Messages.*`, `Services.IMessageHub`/`MessageHub`/`IDispatcher`/`RxDispatcher`.
- 2c — `Commands.*` (`RelayCommand`, `RelayCommand<T>`, builders, reactive triggers).
- 2d — `Components.*` (base + `ComponentVM<M>` + `ReadonlyComponentVM<M>`).
- 2e — `Composites.*` (base + non-modeled + modeled), including `Current` and child orchestration.
- 2f — `Groups.*`.
- 2g — `Aggregates.*` arities 1–5 (hand-write 1 and 2 first; decide on source generator for 3–5).
- 2h — `Forwarding.*` decorators.
- 2i — `VMx.Extensions.DependencyInjection` companion package.
- 2j — Conformance suite passes every catalog ID.
- 2k — DocFX docs + `docs/getting-started/csharp.md`.
- 2l — `examples/csharp/HelloVMx/` (console) + `examples/csharp/WpfTodoApp/` (WPF).
- 2m — Tag `csharp-v1.0.0`; publish to NuGet.

**Milestone:** `VMx 1.0.0` on NuGet.

### Phase 3 — Python v1.0.0 (~3–5 weeks)

Same TDD discipline; Python conformance suite implemented in parallel with each module.

- 3a–3h: mirror C# sub-steps 2a–2h in Python.
- 3i — Conformance suite passes every catalog ID; cross-language CI confirms parity.
- 3j — `mkdocstrings` docs + `docs/getting-started/python.md`.
- 3k — `examples/python/hello_vmx/` + `examples/python/tk_todo_app/`.
- 3l — Tag `python-v1.0.0`; publish to PyPI.

**Milestone:** `vmx 1.0.0` on PyPI.

### Phase 4 — Polish & launch (~1–2 weeks)

- Wire `tools/build-compatibility-matrix.py` into CI.
- Cross-language announcement / GitHub Release notes.
- Confirm README badges, docs site links, package metadata.
- Optionally register a custom domain for docs.

**Milestone:** Public 1.0 announcement.

### Phase 5+ — Post-1.0

- `VMx.Virtualization` adapter package (C#).
- UI binding helpers (`VMx.Wpf`, `VMx.Avalonia`, `VMx.MAUI`, etc.) if demand surfaces.
- TypeScript flavor (see §13).
- More examples (Avalonia, MAUI, PyQt, Web).
- Spec v1.1 driven by real-world usage.

**Total time to 1.0 on both NuGet and PyPI:** ~9–14 weeks of focused part-time work, dominated by Phases 2 and 3.

---

## 13. Future-language playbook

Adding a new language flavor is engineered to be mechanical. Five steps:

1. **Pick a Rx-equivalent library** — `rxjs` (TS), `kotlinx.coroutines.flow` or `RxKotlin` (Kotlin), `Combine` or `RxSwift` (Swift), `tokio-stream`+`futures` (Rust; requires its own ADR), `chan T`+goroutines (Go; requires its own ADR). The library must support hot streams, ordered emission, multi-subscriber broadcast, and scheduler control.
2. **Add `langs/<lang>/`** per the standard skeleton with the language's idiomatic project file and the same module layout (`lifecycle/`, `messages/`, `services/`, `commands/`, `components/`, `composites/`, `groups/`, `aggregates/`, `forwarding/`, `builders/`).
3. **Wire CI** — copy `python.yml` as the template, swap the toolchain, point `paths:` at `langs/<lang>/**` and `spec/**`. Add a ~30-line scraper to `tools/check-conformance-coverage.py` for the language's test-id convention.
4. **Implement to the spec, write conformance tests in lockstep.** Reading order: `spec/00–02` → `spec/03–04` → `spec/05–09` → `spec/10–11` → `spec/12-conformance.md` plus `spec/fixtures/*.json`.
5. **Ship.** Tag `<lang>-v0.x.y` while gaps remain; tag `<lang>-v1.0.0` once the conformance suite is fully green. Register in `compatibility-matrix.md`. Add `docs/getting-started/<lang>.md` and `docs/api/<lang>/`.

**Cost estimates** (post-1.0, with spec stable):

- TypeScript: ~3–4 weeks. `rxjs` is a near-perfect mapping.
- Kotlin: ~4–6 weeks. `Flow` differs structurally from Rx; message-hub mapping needs care.
- Swift: ~4–6 weeks. Combine is close to Rx; actor model adds threading work.
- Rust: ~6–10 weeks + ADR. No 1:1 Rx port; builder/mutation semantics need rethinking.
- Go: similar to Rust + ADR. Less idiomatic fit.

**Guardrails**

- `0.x` flavors may ship with conformance gaps but must carry an **"experimental — partial conformance"** README badge until 1.0.
- A flavor's `1.0.0` requires 100% conformance against the active spec major. CI enforces this.
- When a language can't meet a spec requirement, the resolution is **a spec ADR**, not a workaround. The spec adapts to the language family or the language opts out — recorded, not silent.

---

## 14. Risks & open questions

### Risks

1. **Conformance catalog completeness.** Vague entries let flavors drift. Mitigation: `spec/fixtures/*.json` data files turn fuzzy English into machine-checkable inputs.
2. **Rx threading parity across languages.** `System.Reactive`, `reactivex`, and `rxjs` differ subtly on back-pressure, error propagation, and disposal-during-emission. Mitigation: `THR-NNN` conformance tests pin these with marble/`TestScheduler` tests in each language.
3. **AggregateVM code generation.** Source-generated arities are elegant but add a compile-time dependency. Mitigation: hand-write arities 1 and 2 first; generate 3–5 only if duplication becomes painful.
4. **"Idiomatic per language" drift.** Different mental models under the same name. Mitigation: spec text is the arbiter; deviations require an ADR.
5. **PyPI/NuGet/npm name availability.** `vmx` may be taken. Mitigation: check in Phase 0; fall back to `vmx-mvvm` or `pyvmx` and document.
6. **Single-maintainer bandwidth.** ~9–14 weeks to 1.0 is a real commitment. Phases 2 and 3 are the absorbers; Phase 1 (spec) is not.

### Open questions to revisit during implementation

- DocFX vs. an alternative C# API doc generator (decide in Phase 2k).
- `uv` vs. `hatchling` vs. `poetry` for the Python build/dev workflow (decide in Phase 0).
- Custom docs domain (defer past 1.0 unless already owned).
- Pre-1.0 Python (`0.x`) release during Phase 3 as a preview (optional).
- Whether to publish `.snupkg` symbol packages from day one (lean yes; flip on at first release).

---

## 15. Summary table

| Axis | Decision |
| --- | --- |
| Port fidelity | Faithful + modernized; comScore eliminated; simplify generics where safe |
| Audience / distribution | Public OSS; NuGet + PyPI (+ npm for future TS); OIDC trusted publishing; GitHub Pages docs |
| C# targets | `netstandard2.0` + `net8.0` multi-target |
| Reactive primitive | Rx everywhere: `System.Reactive` (C#), `reactivex` (Python), `rxjs` (future TS) |
| DI model | Constructor injection; companion `VMx.Extensions.DependencyInjection` package |
| Repo layout | `langs/<lang>/` umbrella + shared `spec/`, `docs/`, `examples/`, `tools/`, `.github/` |
| Virtualization | Dropped from core; optional `VMx.Virtualization` package planned post-1.0 |
| API style | Idiomatic per language; semantic parity enforced by the spec |
| Execution strategy | Spec-first → C# v1.0 → Python v1.0; TS post-1.0 |
| Versioning | Option A: independent SemVer per language + shared spec version + compat matrix |
| Conformance | Stable `XXX-NNN` IDs + JSON fixtures; CI fails on gaps |
| Phasing | 5 phases: scaffolding → spec v1 → C# v1 → Python v1 → polish/launch |
| Future languages | 5-step playbook, additive only, ADR-gated when spec can't be met |
