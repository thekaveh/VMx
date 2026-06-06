# VMx — Swift (skeleton)

Hierarchical lifecycle-aware MVVM viewmodel framework for Swift,
spec-compatible with the C# / Python / TypeScript flavors.

## 1. Status

**v2.4.0 — first release of the Swift flavor.** Covers **53 of 232**
conformance IDs from `spec-v2.4.0`: the lifecycle state machine, the modeled
and unmodeled `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVM1..6`,
`RelayCommand`, and the immutable fluent builders. The remaining 179 IDs
(`HierarchicalVM`, `FormVM`, the 22 capability micro-interfaces,
`DerivedProperty`, observable collections, the notifications sub-package,
threading specifics, forwarding decorators, dialog service, expand/collapse
helpers, the localizer hook, tree utilities) are deferred to a follow-up
Swift release — see §5 for the in / deferred breakdown. Requires Swift 5.9+,
Combine, iOS 16 / macOS 13 / tvOS 16 / watchOS 9.

## 2. Install

Add VMx as a Swift Package dependency in `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/thekaveh/VMx.git", from: "2.4.0")
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
tabs.construct()
print(tabs.status)              // ConstructionStatus.constructed

tabs.current = tab2
print(tabs.current?.model.title) // "Settings"

tabs.dispose()
hub.dispose()
```

The C# / Python / TypeScript flavors mirror this shape — only the
identifier casing differs (per ADR-0006: Swift uses **camelCase**,
matching the TypeScript flavor).

See [docs/integration/swiftui.md](../../docs/integration/swiftui.md) for
a one-page SwiftUI integration recipe.

## 3.4 Cross-language naming

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
| `StatusTransitionError`         | Thrown on illegal lifecycle operations           |
| `BuilderValidationError`        | Thrown when a builder is missing a required field |

## 5. Conformance — subset for this release

This first release implements **a subset** of the cross-language
conformance catalog. The covered IDs are:

```
LIFE-001..013   ComponentVMBase lifecycle state machine
CVM-001..006    ComponentVM / ComponentVMOf identity + model
COMP-001..010   CompositeVM children + current slot (subset)
GRP-001..006    GroupVM peers + cascade (subset)
AGG-001..006    AggregateVM1..AggregateVM6 parametric coverage
CMD-001..007    RelayCommand task + predicate + triggers (subset)
BLD-001..005    Builders immutable + validation + null-services
```

**Deferred to follow-up PRs:**

- `HUB-*` / `PROP-*` — full hub semantics, identity / ordering fixtures,
  late-subscriber and exception isolation rules
- `THR-*` — threading & schedulers, async selection / async construct
- `FWD-*` — forwarding decorators (`ForwardingComponentVM`,
  `ForwardingCompositeVM`)
- `CAP-*` / `NULL-*` / `DPROP-*` — capability micro-interfaces,
  null-object variants beyond the two shipped, `DerivedProperty<T>`
- `CMDD-*` — `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`, `ModeledCrudCommands`
- `NOTIF-*` — opt-in notification sub-package (`INotificationHub`)
- `EXP-*` / `LOC-*` — expand/collapse state, localization hook
- `COL-*` — observable collections, batch updates, paged composition
- `HIER-*` — `HierarchicalVM` recursive tree VM
- `DIA-*` — `IDialogService` host modal interactions
- `FORM-*` — `FormVM` snapshot/revert lifecycle
- `UTIL-*` — tree utilities (`walk`, `walkExpanded`, `find`)
- `LIFE-011` fixture-driven transition table (currently hand-rolled)

The follow-up PR will widen coverage to full parity with the other
three flavors. **This release is NOT yet at 232/232.**

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

MIT
