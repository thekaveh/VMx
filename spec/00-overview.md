# 00 — Overview

VMx is a hierarchical, lifecycle-aware MVVM viewmodel framework. It defines a tree of
viewmodels (components, composites, groups, aggregates), an explicit lifecycle state
machine (`ConstructionStatus`), commands with reactive triggers, and a hot pub/sub
message hub for change notifications. The library is UI-framework-agnostic and ships
in multiple language flavors with semantically equivalent behavior.

## 1. In scope

- Hierarchical viewmodel types: `ComponentVM`, `ReadonlyComponentVM`, `CompositeVM`,
  `GroupVM`, `AggregateVM<VM1..VM6>`.
- Forwarding decorators that wrap an inner viewmodel without becoming new tree
  nodes themselves: `ForwardingComponentVM`, `ForwardingCompositeVM`.
- Lifecycle state machine: `Disposed`, `Destructing`, `Destructed`, `Constructing`,
  `Constructed`, with `Construct ↔ Destruct` reversibility and terminal `Disposed`.
- Commands: `RelayCommand` with predicates and reactive triggers; parameterized
  variant for typed parameters.
- Message hub: hot stream of `IMessage`-derived events, used for property changes and
  lifecycle status changes.
- Fluent immutable builders for every viewmodel and command type.
- Capability micro-interfaces, helpers (`SearchableState`, `ExpandableState`,
  `DerivedProperty`, `ModeledCrudCommands`), null-object services, optional
  `INotificationHub` sub-package, and `ILocalizer` hook (introduced in spec
  v2.0, detailed in chapters 14–17).
- **v2.1 additions**. New chapters 18–21: `HierarchicalVM<TModel, TVM>` —
  first-class recursive tree VM with lazy/eager child loading and
  `TreeStructureChangedMessage`; `IDialogService` — host-side modal
  interactions distinct from `INotificationHub`; `FormVM<TM>` — snapshot/revert
  edit lifecycle with approve/deny commands and `FormRevertedMessage`;
  collection primitives `ServicedObservableCollection<T>`, `ObservableList<T>`,
  `ObservableDictionary<K1,K2,V>`, and `PagedComposition<TVM>`. Extensions to
  existing chapters: `PropertyValueChangedMessagesFor` batch publisher
  (chapter 03 §7, ADR-0032, informative); fluent command extensions `Confirm`,
  `PrecedeWith`, `SucceedWith`, `WrapWith` (chapter 04 §9, ADR-0027); two new
  capability micro-interfaces `IFilterable<TItem>` (chapter 14 §2.6, ADR-0022) and
  `IPageable` (chapter 14 §2.10, ADR-0023) joining at positions 21 and 22; a
  lazy-initialization recipe for derived properties (chapter 15 §8);
  `NotificationVM` + `ConfirmationVM` render-side VMs with auto-dismiss
  lifecycle (chapter 16 §6–§7, ADR-0031).
- **v2.2 additions**. `AggregateVM6` extends the aggregate family from arity
  5 to arity 6 (chapter 08 §1, ADR-0034); the Notes-Showcase flagship example
  portfolio establishes the cross-flavor scenario contract pattern.
- **v2.3 additions**. `FormVMBuilder<TM>` and `HierarchicalVMBuilder<M, VM>`
  bring the two latest VM kinds into the immutable-builder discipline (ADR-0035);
  conformance gains `FORM-011..013`, `HIER-015..017`, and additive `BLD-005`
  for builder-`Triggers` semantics.
- **v2.4 additions**. New Swift flavor, initially implementing a subset of the spec
  (`langs/swift/` — subsequently brought to full library parity in v3.1.0; see
  langs/swift/README.md §5);
  `ThemeVM` cross-flavor scenario contract (`THEME-001..005`, ADR-0036 §2.C);
  publication-readiness pass (TS npm rename `vmx` → `@thekaveh/vmx`, ADR-0036
  §2.A) and example-app edge-case coverage backfill (ADR-0036 §2.D). No new
  chapter files; the scenario contract lives at
  `spec/proposals/2026-06-02-theme-vm-scenario.md`.
- **v2.5 additions**. Maintenance-pass clarifications (ADR-0037) — Swift
  conformance subset accurately recounted 53 → 39 (corrects ADR-0036 §2.E);
  three new normative IDs added — `HIER-018` (`HierarchicalVM` reparent guard
  against self/ancestor cycles, chapter 18 §6), `NOTIF-017` (`NotificationHub`
  dispose semantics, chapter 16 §9), and `FORM-014` ("disposed form is inert",
  ADR-0038, chapter 20). Catalog total grows 232 → 235 (230 library + 5 THEME).
- **v2.6 additions**. Absorption-audit follow-up — `CompositeVMBuilder` gains
  two declarative selection hooks: `Current(selector)` (`COMP-025`) for
  initial-current selection during construct, and `OnCurrentChanged(callback)`
  (`COMP-026`) for synchronous post-change selection callback (chapter 06 §3.2,
  ADR-0042). Both hooks ship on the non-modeled and modeled composite builders
  in all full-parity flavors — Swift's modeled `CompositeVMOfBuilder` gained `current(...)`
  and `onCurrentChanged(...)` at full parity (ADR-0064). Catalog total grows 235 → 237 (232 library + 5
  THEME). Three teaching ADRs formalize prior-art rejections: ADR-0039
  (`INotifyPropertyChanging` not supported), ADR-0040 (`IProperty<T>` reactive
  backing-field not adopted), ADR-0041 (single disposable lifecycle, no
  two-tier bags). Predecessor folders cleared for follow-up deletion per
  `spec/proposals/2026-06-13-vmx-absorption-audit-followup.md` §10.

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

| Term               | Definition                                                                                                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **VM**             | viewmodel — an instance of one of the VMx types.                                                                                                                             |
| **model**          | the domain object a VM wraps (optional; `Readonly*` and `*Of[M]` variants attach a typed model).                                                                             |
| **parent**         | the composite that owns a VM (a child can have at most one parent).                                                                                                          |
| **current**        | the child currently selected within a composite (at most one per composite).                                                                                                 |
| **predicate**      | a `() -> bool` (or `(T) -> bool`) function deciding whether a command can execute.                                                                                           |
| **trigger**        | an `IObservable<Unit>` whose emissions cause a command's `CanExecute` to be re-evaluated and `CanExecuteChanged` to be raised.                                               |
| **hub**            | the `IMessageHub` instance every VM publishes to and any subscriber can observe.                                                                                             |
| **builder**        | an immutable fluent object that accumulates configuration and produces a VM (or command) via `Build()`.                                                                      |
| **dispatcher**     | `IDispatcher` exposes a foreground and a background Rx scheduler; VMs use them to dispatch property-change events and lifecycle work.                                        |
| **foreground**     | the Rx scheduler reserved for events that subscribers expect on the UI thread (e.g., `PropertyChanged`, collection notifications).                                           |
| **background**     | the Rx scheduler used for VM construction/destruction work that should not block the foreground.                                                                             |
| **conformance ID** | a stable `XXX-NNN` identifier in `12-conformance.md`; all five library suites implement the 396 library IDs, while `THEME-00x` IDs apply to UI-backed flagship applications. |

## 4. Audience

This spec is the contract that every language implementation MUST satisfy. The
audience is implementers of language flavors and contributors who change the
semantics of any VM type or service.

End-user documentation (getting-started guides, API reference) is generated per
language and lives under `docs/`.

## 5. Document conventions

- **MUST** / **MUST NOT** / **SHOULD** / **MAY** follow RFC 2119.
- Pseudo-signatures use generic notation (`ComponentVM<M>`, `IList<VM>`); each
  language flavor renders these in its native syntax.
- Cross-references use `§N` for sections of the same document and the filename
  (`02-lifecycle.md`) for sections of other documents.

## 6. C#-only extensions

The C# flavor ships one utility that has no counterpart in the other four flavors:
`LinqHelpers` (in `VMx.Extensions`) — a small set of LINQ utility methods over
`IEnumerable<T>`: `CartesianProduct`, `Sample`, and `Product`. Python,
TypeScript, Swift, and Rust cover the same use-cases through their standard
library collection and iterator facilities rather than VMx wrappers. This
asymmetry is intentional and documented in ADR-0033.
