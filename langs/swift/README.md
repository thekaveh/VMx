# VMx — Swift (skeleton)

Hierarchical lifecycle-aware MVVM viewmodel framework for Swift,
spec-compatible with the C# / Python / TypeScript flavors.

## 1. Status

**v3.0.0 (subset).** Covers **94 of 237**
conformance IDs from `spec-v3.0.0` (recounted honestly in ADR-0037; +COMP-025/COMP-026 added per ADR-0042; +LIFE-008 via the v3 throwing-convergence in ADR-0053; +50 leaf-area IDs via Phase-3 Inc-1 — ADR-0059): the lifecycle state machine, the modeled
and unmodeled `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM1..6`,
`RelayCommand`, the immutable fluent builders, `DerivedProperty<T>`, the
22 capability micro-interfaces, null objects (`NullMessageHub`, `NullDispatcher`,
`NullLocalizer`), localization hook (`Localizer` / `NullLocalizer`), tree
utilities (`walk`, `find`, `walkExpanded`), hub property accessors, and
forwarding decorators (`ForwardingComponentVM`, `ForwardingCompositeVM`). The
remaining 143 IDs (`HierarchicalVM`, `FormVM`, observable collections, the
notifications sub-package, threading specifics, dialog service,
expand/collapse state, composite-current commands) are deferred to follow-up
Swift releases — see §5 for the in / deferred breakdown. Requires Swift 5.9+,
Combine, iOS 16 / macOS 13 / tvOS 16 / watchOS 9.

## 2. Install

Add VMx as a Swift Package dependency in `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/thekaveh/VMx.git", from: "3.0.0")
],
targets: [
    .target(name: "MyApp", dependencies: [
        .product(name: "VMx", package: "VMx")
    ])
]
```

Or in Xcode: **File → Add Package Dependencies → enter the repo URL**.

## 3. Quick start

```swift
import VMx

struct TabModel: Equatable {
    let title: String
}

// 1. Services (a hub + a dispatcher).
let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

// 2. Build leaves: name, model, services, optional modeledHinter.
let tab1 = try ComponentVMOf<TabModel>.builder()
    .name("home")
    .model(TabModel(title: "Home"))
    .modeledHinter { $0.title }
    .services(hub: hub, dispatcher: dispatcher)
    .build()

let tab2 = try ComponentVMOf<TabModel>.builder()
    .name("settings")
    .model(TabModel(title: "Settings"))
    .services(hub: hub, dispatcher: dispatcher)
    .build()

// 3. Build a composite over the leaves.
let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
    .name("tab-bar")
    .services(hub: hub, dispatcher: dispatcher)
    .children { [tab1, tab2] }
    .build()

// 4. Transition the lifecycle from .destructed → .constructed before use.
//    Lifecycle ops are throwing in v3 (ADR-0053): an illegal transition raises
//    a catchable `StatusTransitionError` instead of trapping.
try tabs.construct()
print(tabs.status)              // ConstructionStatus.constructed

tabs.current = tab2             // setter traps on a non-child; use
                               // try tabs.setCurrent(tab2) for a catchable check
print(tabs.current?.model.title) // "Settings"

tabs.dispose()                  // dispose() is terminal/idempotent — never throws
hub.dispose()
```

The C# / Python / TypeScript flavors mirror this shape — only the
identifier casing differs (per ADR-0006: Swift uses **camelCase**,
matching the TypeScript flavor).

See [docs/integration/swiftui.md](../../docs/integration/swiftui.md) for
a one-page SwiftUI integration recipe.

### 3.1 Cross-language naming

| Concept             | C#                  | Python             | TypeScript         | Swift              |
| ------------------- | ------------------- | ------------------ | ------------------ | ------------------ |
| Unmodeled VM        | `ComponentVM`       | `ComponentVM`      | `ComponentVM`      | `ComponentVM`      |
| Modeled VM          | `ComponentVM<M>`    | `ComponentVMOf[M]` | `ComponentVMOf<M>` | `ComponentVMOf<M>` |
| Status property     | `Status`            | `status`           | `status`           | `status`           |
| Builder entrypoint  | `Builder()`         | `builder()`        | `builder()`        | `builder()`        |
| Null hub singleton  | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

## 4. API surface (skeleton)

```swift
import VMx
```

Key exports:

| Export                          | Description                                      |
| ------------------------------- | ------------------------------------------------ |
| `ComponentVM`                   | Leaf viewmodel (no model)                        |
| `ComponentVMOf<M>`              | Leaf viewmodel with a typed model                |
| `ReadonlyComponentVMOf<M>`      | Leaf VM with externally read-only model          |
| `CompositeVM<VM>`               | Homogeneous-child container + `current` slot     |
| `GroupVM<VM>`                   | Homogeneous peer container (no current)          |
| `AggregateVM1..6<...>`          | Fixed-arity heterogeneous component slots        |
| `RelayCommand`                  | Executable command with `canExecute`             |
| `MessageHub` / `NullMessageHub.INSTANCE` | Combine-backed pub/sub + null variant   |
| `Dispatcher`                    | Foreground/background work scheduler protocol    |
| `DefaultDispatcher`             | Main + global-userInitiated Dispatch wrapper     |
| `ImmediateDispatcher.INSTANCE`  | Synchronous test dispatcher                      |
| `NullDispatcher.INSTANCE`       | Null-object variant per ADR-0017                 |
| `ConstructionStatus`            | 5-state lifecycle enum                           |
| `StatusTransitionError`         | Thrown on an illegal lifecycle op / `LIFE-008` guard (catchable — ADR-0053) |
| `CompositeMembershipError`      | Thrown by `CompositeVM.setCurrent(_:)` on a non-child (ADR-0053) |
| `BuilderValidationError`        | Thrown when a builder is missing a required field |

## 5. Conformance — subset for this release

This flavor implements **a subset** of the cross-language conformance
catalog. The **94 covered IDs** (Inc-0: 44 base IDs per ADR-0037/ADR-0053;
Inc-1: +50 leaf-area IDs per ADR-0059) are:

```
LIFE-001..014   lifecycle state machine + fixture-driven transition table
                (LIFE-005/006/008 assert catchable throws — ADR-0053;
                LIFE-011 fixture-backed table now covered via Bundle.module)
CVM-001..006    ComponentVM / ComponentVMOf identity + model
                (CVM-003: read-only model setter still traps —
                Swift setters cannot throw — per ADR-0053)
COMP-003..005,  select-through-child + lifecycle cascades +
COMP-025/026    builder `current(selector)` / `onCurrentChanged(callback)` hooks
GRP-002..004    group surface contract + lifecycle cascades
AGG-001..006    AggregateVM1..AggregateVM6 parametric coverage
CMD-001..004, 006   RelayCommand task + predicate + triggers
BLD-001..005    builders immutable + validation + defaults
PROP-001..004   hub property-change accessors
NULL-001..003   NullMessageHub + NullDispatcher + NullLocalizer
LOC-001..003    Localizer protocol + NullLocalizer null-object (no I-prefix — ADR-0006)
UTIL-001..003   walk + find + walkExpanded tree utilities (materialized arrays)
FWD-001..003    ForwardingComponentVM + ForwardingCompositeVM decorators
                (name/hint copied at super.init — non-overridable let — ADR-0059;
                composite surface mirrors real CompositeVM, no insert/setAt/clear)
DPROP-001..012  DerivedProperty<T> — setValue(_:) throws / value() is a method;
                distinct-until-changed via valueEquals closure (ADR-0059)
CAP-001..022    22 capability micro-interfaces — generic verbs use associatedtype
                Item (PAT); opt-in by structural conformance (as?/is); reactive
                state via Combine publishers (ADR-0059)
```

Not claimed (behavior not implemented yet): `CVM`-adjacent CollectionChanged
events (`COMP-001/002`, `GRP-001`), foreground-dispatch IDs (`COMP-006/010`),
`COMP-007/008/009`, `GRP-005/006` (AutoConstructOnAdd / BatchUpdate),
`CMD-005` (parameterized variant), and `CMD-007` (truth-table fixture).

**Deferred to follow-up PRs:**

- `HUB-*` — full hub semantics, identity / ordering fixtures,
  late-subscriber and exception isolation rules
- `THR-*` — threading & schedulers, async selection / async construct
- `CMDD-*` — `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, `ModeledCrudCommands`
- `NOTIF-*` — opt-in notification sub-package (`INotificationHub`)
- `EXP-*` — expand/collapse state (distinct from `walkExpanded` — the state
  machine and `COMP-009` current-guard are deferred)
- `COL-*` — observable collections, batch updates, paged composition
- `HIER-*` — `HierarchicalVM` recursive tree VM
- `DIA-*` — `IDialogService` host modal interactions
- `FORM-*` — `FormVM` snapshot/revert lifecycle

**This release is NOT yet at full parity with the 237-ID catalog.**

Run the suite:

```bash
swift test
```

## 6. Development

```bash
# From this directory
swift build
swift test
```

## 7. License

Apache-2.0 — see [`LICENSE`](../../LICENSE) and [`NOTICE`](../../NOTICE).
