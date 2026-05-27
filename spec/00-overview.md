# 00 — Overview

VMx is a hierarchical, lifecycle-aware MVVM viewmodel framework. It defines a tree of
viewmodels (components, composites, groups, aggregates), an explicit lifecycle state
machine (`ConstructionStatus`), commands with reactive triggers, and a hot pub/sub
message hub for change notifications. The library is UI-framework-agnostic and ships
in multiple language flavors with semantically equivalent behavior.

## In scope

- Hierarchical viewmodel types: `ComponentVM`, `ReadonlyComponentVM`, `CompositeVM`,
  `GroupVM`, `AggregateVM<VM1..VM5>`, `ForwardingComponentVM`, `ForwardingCompositeVM`.
- Lifecycle state machine: `Disposed`, `Destructing`, `Destructed`, `Constructing`,
  `Constructed`, with `Construct ↔ Destruct` reversibility and terminal `Disposed`.
- Commands: `RelayCommand` with predicates and reactive triggers; parameterized
  variant for typed parameters.
- Message hub: hot stream of `IMessage`-derived events, used for property changes and
  lifecycle status changes.
- Fluent immutable builders for every viewmodel and command type.
- Capability micro-interfaces, helpers (`SearchableState`, `ExpandableState`,
  `DerivedProperty`, `ModeledCrudCommands`), null-object services, optional
  `INotificationHub` sub-package, and `ILocalizer` hook (introduced in spec v2.0,
  detailed in chapters 14–17).

## Out of scope

- UI bindings. VMs expose `INotifyPropertyChanged`-equivalent semantics; the rendering
  layer is the host application's responsibility.
- Virtualization. See ADR-0005.
- Navigation routing, persistence, serialization. These are application concerns, not
  framework concerns.
- A unified, locked-step version across language flavors. Each flavor versions
  independently; the spec version is the shared anchor (see ADR-0006 for the
  idiomatic-per-language stance).

## Glossary

| Term               | Definition                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| **VM**             | viewmodel — an instance of one of the VMx types.                                                                                      |
| **model**          | the domain object a VM wraps (optional; `Readonly*` and `*Of[M]` variants attach a typed model).                                      |
| **parent**         | the composite that owns a VM (a child can have at most one parent).                                                                   |
| **current**        | the child currently selected within a composite (at most one per composite).                                                          |
| **predicate**      | a `() -> bool` (or `(T) -> bool`) function deciding whether a command can execute.                                                    |
| **trigger**        | an `IObservable<Unit>` whose emissions cause a command's `CanExecute` to be re-evaluated and `CanExecuteChanged` to be raised.        |
| **hub**            | the `IMessageHub` instance every VM publishes to and any subscriber can observe.                                                      |
| **builder**        | an immutable fluent object that accumulates configuration and produces a VM (or command) via `Build()`.                               |
| **dispatcher**     | `IDispatcher` exposes a foreground and a background Rx scheduler; VMs use them to dispatch property-change events and lifecycle work. |
| **foreground**     | the Rx scheduler reserved for events that subscribers expect on the UI thread (e.g., `PropertyChanged`, collection notifications).    |
| **background**     | the Rx scheduler used for VM construction/destruction work that should not block the foreground.                                      |
| **conformance ID** | a stable `XXX-NNN` identifier (e.g., `CVM-001`) in `12-conformance.md` that every language flavor MUST implement as a passing test.   |

## Audience

This spec is the contract that every language implementation MUST satisfy. The
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
