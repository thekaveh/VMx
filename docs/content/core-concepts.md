# 4. Core Concepts

## 4.1. One Spec, Five Source Flavors

VMx is defined once in `spec/` and implemented idiomatically in C#, Python,
TypeScript, Swift, and Rust. The conceptual model stays aligned even when
naming changes by flavor.

## 4.2. Lifecycle-Aware ViewModels

Every VM participates in the same construction state machine:
`Destructed`, `Constructing`, `Constructed`, `Destructing`, and terminal
`Disposed`. Construction, destruction, reconstruction, and disposal are part of
the framework contract rather than host-app convention.

Disposal itself is framework-wide and idempotent: independent teardown paths
may call it without consumer-side coordination. The complete per-type behavior
is in the [Disposal Contract](primitives/disposal-contract.md).

## 4.3. Message Hub and Dispatcher

Each VM receives a message hub and dispatcher. The hub carries property and
lifecycle messages across the tree, while the dispatcher centralizes foreground
and background scheduling for reactive work.

## 4.4. Parent-Child Ownership

Leaf `ComponentVM`s model a single node. `CompositeVM`, `GroupVM`, and
`AggregateVM1..6` define ownership and traversal rules for children. Parent
references, depth-first lifecycle cascades, and current-selection semantics are
part of the shared shape.

## 4.5. Shared VM Collections

Groups and composites implement one ordered observable collection capability.
Selection is a separate extension implemented only by composites. The shared
atomic move operation changes order without replacing, reconstructing,
reparenting, or deselecting the child; see the
[VM Collection Contract](primitives/vm-collection-contract.md).

## 4.6. Idiomatic Naming by Flavor

| Flavor     | Naming style                              |
| ---------- | ----------------------------------------- |
| C#         | PascalCase                                |
| Python     | snake_case                                |
| TypeScript | camelCase                                 |
| Swift      | camelCase                                 |
| Rust       | snake_case methods, Rust-style type names |

Message payload property names follow the local idiom, with the documented
`Count` channel exception for collection messages.

## 4.7. Conformance Catalog

The spec defines 422 conformance IDs: 417 library IDs plus 5 `THEME-00x`
scenario IDs. Every catalog-complete flavor carries the 417 library IDs in its own
conformance suite, and repository tooling checks coverage before CI passes.

## 4.8. Framework Surface

Every flavor exposes the same surface under its own naming idiom:

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
  re-evaluation notifications, plus the decorators `CompositeCommand`,
  `DecoratorCommand`, and `ConfirmationDecoratorCommand`, and a modeled-CRUD
  helper (`ModeledCrudCommands`).
- Tree utilities (`walk`, `find`, `walk_expanded`) for introspection.
- 22 opt-in capability micro-interfaces (`ISelectable`, `IExpandable`,
  `IClosable`, `IFilterable`, `IPageable`, …) and helper state classes
  (`ExpandableState`, `SearchableState`) for layering behaviour onto VMs
  additively. `SearchableState` optionally observes a source-change signal so
  an unchanged term stays synchronized with collection or member invalidations.
- `DerivedProperty<T>` for N-source computed values, `FormVM<T>` for
  snapshot/revert/validation flows, `DiscriminatorVM` for single-active-key
  coordination, `AsyncResourceVM<T>` for cancellable latest-wins acquisition,
  `PagedComposition` / `TokenPagedComposition` for finite and cursor paging,
  an opt-in notification sub-package (`INotificationHub`), `IDialogService`,
  null-object service variants (`NullMessageHub`, `NullDispatcher`,
  `NullNotificationHub`, `NullLocalizer`, `NullDialogService`), and an
  `ILocalizer` hook for i18n.

[Framework Primitives](primitives/index.md) explains when to reach for each
family.
