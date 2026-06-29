# VMx — Swift (skeleton)

Hierarchical lifecycle-aware MVVM viewmodel framework for Swift,
spec-compatible with the C# / Python / TypeScript flavors.

## 1. Status

**v3.0.0 (subset).** Covers **124 of 237**
conformance IDs from `spec-v3.0.0` (recounted honestly in ADR-0037; +COMP-025/COMP-026 added per ADR-0042; +LIFE-008 via the v3 throwing-convergence in ADR-0053; +50 leaf-area IDs via Phase-3 Inc-1 — ADR-0059; +30 collections IDs via Phase-3 Inc-2 — ADR-0060): the lifecycle state machine, the modeled
and unmodeled `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM1..6`,
`RelayCommand`, the immutable fluent builders, `DerivedProperty<T>`, the
22 capability micro-interfaces, null objects (`NullMessageHub`, `NullDispatcher`,
`NullLocalizer`), localization hook (`Localizer` / `NullLocalizer`), tree
utilities (`walk`, `find`), hub property accessors,
forwarding decorators (`ForwardingComponentVM`, `ForwardingCompositeVM`), and
observable collections (`ObservableList`, `ObservableDictionary`,
`ServicedObservableCollection`, `PagedComposition`, collection-changed events,
batch updates, auto-construct). The
remaining 113 IDs (`HierarchicalVM`, `FormVM`, the
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
catalog. The **141 covered IDs** (Inc-0: 44 base IDs per ADR-0037/ADR-0053;
Inc-1: +50 leaf-area IDs per ADR-0059; Inc-2: +30 collections IDs per ADR-0060;
Inc-3: +9 HIER tree-identity + expand/collapse EXP + HIER mutation IDs) are:

```
LIFE-001..014   lifecycle state machine + fixture-driven transition table
                (LIFE-005/006/008 assert catchable throws — ADR-0053;
                LIFE-011 fixture-backed table now covered via Bundle.module)
CVM-001..006    ComponentVM / ComponentVMOf identity + model
                (CVM-003: read-only model setter still traps —
                Swift setters cannot throw — per ADR-0053)
COMP-001/002,   CollectionChanged events on CompositeVM (Inc-2 — ADR-0060)
COMP-003..005,  select-through-child + lifecycle cascades +
COMP-025/026    builder `current(selector)` / `onCurrentChanged(callback)` hooks
COMP-012/013    autoConstructOnAdd + BatchUpdateHandle (Inc-2 — ADR-0060;
                assertionFailure on construct failure; explicit dispose() safety net)
GRP-001..004    group surface contract + lifecycle cascades + CollectionChanged (Inc-2)
GRP-005/006     autoConstructOnAdd + BatchUpdateHandle on GroupVM (Inc-2 — ADR-0060)
AGG-001..006    AggregateVM1..AggregateVM6 parametric coverage
CMD-001..004, 006   RelayCommand task + predicate + triggers
BLD-001..005    builders immutable + validation + defaults
PROP-001..004   hub property-change accessors
NULL-001..003   NullMessageHub + NullDispatcher null-object contracts
LOC-001..003    Localizer protocol + NullLocalizer null-object (no I-prefix — ADR-0006)
UTIL-001..003   walk (DFS, nil-slot skip) + find (short-circuit) tree utilities
                (materialized arrays)
FWD-001..003    ForwardingComponentVM + ForwardingCompositeVM decorators
                (name/hint copied at super.init — non-overridable let — ADR-0059;
                composite surface mirrors real CompositeVM)
DPROP-001..012  DerivedProperty<T> — setValue(_:) throws / value is a throwing property;
                distinct-until-changed via valueEquals closure (ADR-0059)
CAP-001..022    22 capability micro-interfaces — generic verbs use associatedtype
                Item (PAT); opt-in by structural conformance (as?/is); reactive
                state via Combine publishers (ADR-0059)
COL-001..023    ObservableList, ObservableDictionary, ServicedObservableCollection,
                PagedComposition (Inc-2 — ADR-0060):
                "Count" channel is spec-literal (not Swift-idiomatic "count");
                ObservableDictionary null-key enforcement is structural
                (non-optional generic key + struct CompositeKey: Hashable);
                PagedComposition uses setSource(_:) (value-semantics);
                CollectionChangedEvent/Message are value-type structs with
                CollectionChangedAction enum + named-struct per-mutation payloads
EXP-001..005    ExpandableState machine (isExpanded / toggle / expand / collapse)
                + walkExpanded DFS expansion-gated traversal (Inc-3)
HIER-001..009   HierarchicalVM tree identity — recursive CRTP constraint,
                parent/depth/path/isLeaf/isRoot/isFirst/isLast, lazy + eager
                child construction, depth-first ordering (Inc-3)
HIER-010/011    addChild/removeChild/reparentChild hub notifications —
                PropertyChangedMessage("parent") + TreeStructureChangedMessage
                (added/removed/reparented shapes) (Inc-3)
HIER-018        reparentChild self/ancestor guard — throws HierarchyError,
                tree unchanged, no message published on rejection (Inc-3)
```

Not yet claimed: `CMD-005` (parameterized variant) and `CMD-007`
(truth-table fixture).

**Deferred to follow-up PRs:**

- `HUB-*` — full hub semantics, identity / ordering fixtures,
  late-subscriber and exception isolation rules
- `THR-*` — threading & schedulers, async selection / async construct
- `CMDD-*` — `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, `ModeledCrudCommands`
- `NOTIF-*` — opt-in notification sub-package (`INotificationHub`)
- `COMP-006/010` — foreground-dispatch / async selection (Increment 3,
  threading)
- `COMP-007` — modeled composite
- `COMP-008/011` — selection-membership validation
- `COMP-014..024`, `GRP-007..010` — SearchableState / CRUD context IDs
  (land with forms/hub in Increment 4)
- `HIER-012..017`, `HIER-019..` — remaining HierarchicalVM IDs (walkExpanded,
  name defaulting, builder, expand-capability composition, etc.)
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
