# 00 — Overview

VMx is a hierarchical, lifecycle-aware MVVM viewmodel framework. It defines a tree of
viewmodels (components, composites, groups, aggregates), an explicit lifecycle state
machine (`ConstructionStatus`), commands with reactive triggers, and a hot pub/sub
message hub for change notifications. The library is UI-framework-agnostic and ships
in multiple language flavors with semantically equivalent behavior.

## 1. In scope

The spec covers these areas. [`README.md`](README.md) lists every chapter, and
[`HISTORY.md`](HISTORY.md) records when each area arrived.

| Area                    | What the spec defines                                                                                   | Chapters           |
| ----------------------- | ------------------------------------------------------------------------------------------------------- | ------------------ |
| Core model              | Viewmodel families, lifecycle state machine, message hub, commands                                      | 01, 02, 03, 04     |
| Viewmodel types         | `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM<VM1..VM6>`, forwarding decorators                 | 05, 06, 07, 08, 09 |
| Specialized viewmodels  | `HierarchicalVM` and `TreeSelection`, `FormVM`, `DiscriminatorVM`, `AsyncResourceVM`                    | 18, 20, 22, 23     |
| Construction, threading | Immutable fluent builders; dispatchers, the scheduler contract and `DelayedTask`                        | 10, 11             |
| Opt-in helpers          | Tree utilities, capability interfaces, `DerivedProperty`, notifications, `ILocalizer`, `IDialogService` | 13–17, 19          |
| Collections             | Collection primitives, paging, `AggregateChangeStream`                                                  | 21                 |
| Conformance             | The cross-language test catalog that every flavor implements                                            | 12                 |

## 2. Out of scope

- UI bindings. VMs expose `INotifyPropertyChanged`-equivalent semantics; the rendering
  layer is the host application's responsibility.
- Virtualization. See ADR-0005.
- Navigation routing, persistence, serialization. These are application concerns, not
  framework concerns.
- A unified, locked-step version across language flavors. Each flavor versions
  independently; the spec version is the shared anchor (see ADR-0006 for the
  idiomatic-per-language stance).

## 3. Glossary

| Term               | Definition                                                                                                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **VM**             | viewmodel — an instance of one of the VMx types.                                                                                                                          |
| **model**          | the domain object a VM wraps (optional; `Readonly*` and `*Of[M]` variants attach a typed model).                                                                          |
| **parent**         | the composite that owns a VM (a child can have at most one parent).                                                                                                       |
| **current**        | the child currently selected within a composite (at most one per composite).                                                                                              |
| **predicate**      | a `() -> bool` (or `(T) -> bool`) function deciding whether a command can execute.                                                                                        |
| **trigger**        | an `IObservable<Unit>` whose emissions raise a command's `CanExecuteChanged`, so consumers re-read `CanExecute`.                                                          |
| **hub**            | the `IMessageHub` instance every VM publishes to and any subscriber can observe.                                                                                          |
| **builder**        | an immutable fluent object that accumulates configuration and produces a VM (or command) via `Build()`.                                                                   |
| **dispatcher**     | `IDispatcher` exposes a foreground and a background Rx scheduler; VMs use them to dispatch property-change events and lifecycle work.                                     |
| **foreground**     | the Rx scheduler reserved for events that subscribers expect on the UI thread (e.g., `PropertyChanged`, collection notifications).                                        |
| **background**     | the Rx scheduler used for VM construction/destruction work that should not block the foreground.                                                                          |
| **conformance ID** | a stable `XXX-NNN` identifier in `12-conformance.md`; all five library suites implement every library ID, while `THEME-00x` IDs apply to UI-backed flagship applications. |

## 4. Audience

This spec is the contract that every language implementation MUST satisfy. The
audience is implementers of language flavors and contributors who change the
semantics of any VM type or service.

End-user documentation is hand-written under `docs/content/`: getting-started
guides, primitive and flavor pages, and examples. `docs/manifest.yaml` orders
these pages, and the repository generates the documentation site and the wiki
from them. Each flavor's `langs/<lang>/README.md` documents its package.

## 5. Document conventions

- **MUST** / **MUST NOT** / **SHOULD** / **MAY** follow RFC 2119.
- Pseudo-signatures use generic notation (`ComponentVM<M>`, `IList<VM>`); each
  language flavor renders these in its native syntax.
- A cross-reference to a section of the same document uses `§N`. A
  cross-reference to another chapter uses `chapter NN §N`; older text also uses
  the file name with the section (`02-lifecycle.md` §N). Both forms name a
  numbered section, not a heading title.

## 6. C#-only extensions

The C# flavor does not ship a C#-only utility extension. Earlier C# releases
shipped `LinqHelpers` (in `VMx.Extensions`), a small set of LINQ utility methods
over `IEnumerable<T>`: `CartesianProduct`, `Sample`, and `Product`. ADR-0052
removed it in v3.0.0 because these methods are not part of the viewmodel domain.
ADR-0033 records the original asymmetry. C#, Python, TypeScript, Swift, and Rust
cover the same use-cases through their standard library collection and iterator
facilities rather than VMx wrappers.
