# VMx — Swift

Hierarchical lifecycle-aware MVVM viewmodel framework for Swift,
spec-compatible with the C# / Python / TypeScript / Rust flavors.

## 1. Status

**v3.31.0 source — total parity.** Swift implements `spec-v3.30.0` and covers
all **429 of 429** library conformance IDs. The SwiftUI notes-showcase exercises
the five additional `THEME-00x` scenarios, for **434 total**, matching the other
UI-backed flavors; Rust covers the 429 library IDs and has no UI scenario suite.
See [CHANGELOG.md](CHANGELOG.md) for history.

The package requires Combine and iOS 16, macOS 13, tvOS 16, or watchOS 9. The
manifest declares Swift tools 5.9, but CI builds and tests only with Swift 6.0
(Xcode 16.0) and later, so earlier compilers are untested. The macOS SwiftUI
flagship is at `examples/swift/notes-showcase/`; see §5.

## 2. Install

VMx Swift 3.24.0 (implements spec 3.23.x) is publicly installable from the
repository root. SwiftPM resolves the immutable semantic tag `v3.24.0`; the
matching operational tag `swift-v3.24.0` provides the
[GitHub Release](https://github.com/thekaveh/VMx/releases/tag/swift-v3.24.0).

Add VMx as a Swift Package dependency in `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/thekaveh/VMx.git", from: "3.24.0")
],
targets: [
    .target(name: "MyApp", dependencies: [
        .product(name: "VMx", package: "vmx")
    ])
]
```

Or in Xcode: **File → Add Package Dependencies → enter the repo URL**.

For local development from a checked-out clone:

```swift
dependencies: [
    .package(path: "/path/to/VMx")
]
```

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
print(tabs.status)              // constructed

tabs.current = tab2             // setter traps on a non-child; use
                               // try tabs.setCurrent(tab2) for a catchable check
print(tabs.current?.model.title ?? "(none)") // Settings

tabs.dispose()                  // dispose() is terminal/idempotent — never throws
hub.dispose()
```

The C# / Python / TypeScript flavors mirror this shape — only the
identifier casing differs (per ADR-0006: Swift uses **camelCase**,
matching the TypeScript flavor).

See [SwiftUI Integration](../../docs/content/integration/swiftui.md) for
a one-page SwiftUI integration recipe.

### 3.1 Cross-language naming

The concepts are identical across the five flavors; identifier casing follows
each language idiom (ADR-0006). See the
[cross-language naming table](../../docs/content/flavors/cross-language-naming.md).

## 4. API surface

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
| `VMCollection`                  | Shared group/composite collection + atomic move  |
| `SelectableVMCollection`       | Composite-only current-selection extension       |
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
| `ServicedObservableCollection<T>` | Complete local-before-hub mutation surface |
| `KeyedServicedObservableCollection<Key, T>` | Ordered serviced surface plus captured-key index |
| `ObservableMembershipSource` / `AggregateChangeStream<Item>` | Dynamic membership-and-item fan-in with provenance |
| `ObservableList<T>`             | Granular events, batch scopes, and atomic `replaceAll` |
| `subscribeValue`                | Fixed-VM selected-state bridge returning `AnyCancellable` |

### 4.1 Serviced collections

`ServicedObservableCollection<T>` is a caller-owned sequence that publishes
through Combine locally and then through an optional hub.
`KeyedServicedObservableCollection<Key,T>` adds a captured stable-key index
(`get`, `upsert`, `delete`, `containsKey`) with throwing, atomic projecting
mutations. `move` throws `VMCollectionIndexError`; `removeAt` / `replace` keep
array-precondition bounds behavior. Use `ObservableList<T>` for batching and
`Count` notifications. See
[Swift serviced collections](../../docs/content/flavors/swift.md#753-serviced-collections).

### 4.2 Imperative engine bridge

`subscribeValue` pushes a selected value from one fixed VM into an imperative
host as `(current, previous)`. It returns an `AnyCancellable` that the host
owns; VMx does not attach it to the observed VM's lifetime. See
[Swift imperative engine bridge](../../docs/content/flavors/swift.md#754-imperative-engine-bridge).

## 5. Conformance

Swift implements all 429 library conformance IDs. The
`examples/swift/notes-showcase/` flagship covers `THEME-001..005` in
`ThemeVMTests.swift`, validated by the `examples (notes-showcase)` job in
`.github/workflows/swift.yml`. See
[`spec/12-conformance.md`](../../spec/12-conformance.md) for the catalog and
[`spec/HISTORY.md`](../../spec/HISTORY.md) for the release that added each
group of IDs.

Known Swift divergences:

- The read-only model setter traps because Swift setters cannot throw
  (ADR-0053).
- The `CompositeVM.current` setter traps on a non-child; use
  `try setCurrent(_:)` for a catchable `CompositeMembershipError` (ADR-0053).
- Hub handler traps are uncatchable on every path. `subscribe(_:)` isolates
  thrown errors per subscriber; raw `messages` Combine sinks cannot throw
  (ADR-0062 §2.4).
- `NotificationVM` time values are `TimeInterval` seconds (ADR-0063 §2.4).

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
