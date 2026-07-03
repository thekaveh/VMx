# Getting Started with VMx — Swift

This tutorial walks you through building viewmodels with the VMx Swift
package. You will build a `ComponentVMOf<UserModel>`, a `RelayCommand`, and a
`CompositeVM<TabVM>` with tab selection — all in a Swift Package or playground.

> The Swift flavor is at full parity as of v3.1.0: 281/281 library
> conformance IDs plus the 5 `THEME-00x` scenario IDs covered by the SwiftUI
> Notes Workspace flagship. See
> [`langs/swift/README.md` §5](../../langs/swift/README.md) for the current
> matrix and documented Swift-specific divergences.
>
> For the normative contracts behind each type, see `spec/05-component-vm.md`,
> `spec/04-commands.md`, and `spec/06-composite-vm.md`.

______________________________________________________________________

## 1. Install

The source tree currently implements v3.1.0. SwiftPM consumes VMx from git
tags; use the versioned dependency after a `swift-v*` release publishes it.

Add VMx as a Swift Package dependency in `Package.swift`:

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MyApp",
    platforms: [
        .iOS(.v16), .macOS(.v13), .tvOS(.v16), .watchOS(.v9),
    ],
    dependencies: [
        .package(url: "https://github.com/thekaveh/VMx.git", from: "X.Y.Z"),
    ],
    targets: [
        .target(name: "MyApp", dependencies: [
            .product(name: "VMx", package: "VMx"),
        ]),
    ]
)
```

Or in Xcode: **File → Add Package Dependencies → enter
`https://github.com/thekaveh/VMx.git`**.

For local development from a checked-out clone, use a path dependency:

```swift
.package(path: "/path/to/VMx/langs/swift")
```

The Swift package uses Combine for reactive primitives and Dispatch for
scheduling. No additional dependencies are required.

______________________________________________________________________

## 2. Wire up `MessageHub` and a `Dispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your scheduler pair.

### 2.1 Option A — immediate (test suites / synchronous scripts)

```swift
import VMx

let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE
// Both foreground and background run synchronously on the calling thread.
// Safe for XCTest suites with no async event loop.
```

### 2.2 Option B — default (SwiftUI / UIKit / AppKit apps)

```swift
import VMx

let hub = MessageHub()
let dispatcher = DefaultDispatcher()
// foreground → DispatchQueue.main
// background → DispatchQueue.global(qos: .userInitiated)
```

______________________________________________________________________

## 3. Build a `ComponentVMOf<UserModel>`

`ComponentVMOf<M>` is the primary leaf viewmodel. It holds a typed model,
fires `PropertyChangedMessage` on the hub when the model changes, and
participates in the lifecycle state machine
(`destructed → constructing → constructed → destructing → destructed`).

```swift
import VMx

struct UserModel: Equatable {
    let name: String
    let email: String
}

let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

// Build the viewmodel — every builder setter returns a NEW builder (immutable).
let userVM = try ComponentVMOf<UserModel>.builder()
    .name("user-card")
    .model(UserModel(name: "Alice", email: "alice@example.com"))
    .services(hub: hub, dispatcher: dispatcher)
    // Derive a display hint from the model.
    .modeledHinter { $0.name }
    // Optional callbacks.
    .onConstruct { print("user-card constructed") }
    .onDestruct  { print("user-card destructed")  }
    .build()

// construct() transitions destructed → constructing → constructed.
try userVM.construct()
// stdout: "user-card constructed"

// Update the model.
userVM.model = UserModel(name: "Alice Smith", email: "asmith@example.com")

print(userVM.modeledHint)   // "Alice Smith"
print(userVM.isConstructed) // true
```

> See `spec/05-component-vm.md` for the full component contract.

______________________________________________________________________

## 4. Build a `RelayCommand`

`RelayCommand` wraps an optional `task` closure (the execute body), an
optional `predicate` (the `canExecute` test), and Combine `Publisher`
triggers that signal `canExecute` may have changed. (Builder methods are
`.task(_:)` and `.predicate(_:)`; the resulting command's runtime methods
are `execute()` and `canExecute()` per the cross-language spec.)

```swift
import Combine
import VMx

let canSaveTrigger = PassthroughSubject<Void, Never>()
var isDirty = false

let saveCommand = RelayCommand.builder()
    .task {
        print("Saving…")
        isDirty = false
        canSaveTrigger.send()
    }
    .predicate { isDirty }
    .triggers(canSaveTrigger.eraseToAnyPublisher())
    .build()

print(saveCommand.canExecute()) // false

isDirty = true
canSaveTrigger.send()           // fires canExecuteChanged

print(saveCommand.canExecute()) // true
saveCommand.execute()           // prints "Saving…"
print(saveCommand.canExecute()) // false again

saveCommand.dispose()
```

> See `spec/04-commands.md` for the full command contract.

______________________________________________________________________

## 5. Build a `CompositeVM<TabVM>`

`CompositeVM<VM>` owns an ordered child collection and a `current`
selection slot. Children are provided by a factory that runs on the first
`construct()` call.

```swift
import VMx

struct TabModel: Equatable {
    let title: String
}

let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

let tab1 = try ComponentVMOf<TabModel>.builder()
    .name("home-tab")
    .model(TabModel(title: "Home"))
    .services(hub: hub, dispatcher: dispatcher)
    .build()

let tab2 = try ComponentVMOf<TabModel>.builder()
    .name("settings-tab")
    .model(TabModel(title: "Settings"))
    .services(hub: hub, dispatcher: dispatcher)
    .build()

let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
    .name("tab-bar")
    .services(hub: hub, dispatcher: dispatcher)
    .children { [tab1, tab2] }
    .build()

try tabs.construct()

tabs.current = tab2
print(tabs.current?.model.title ?? "(none)")  // "Settings"

tabs.current = tab1
print(tabs.current?.model.title ?? "(none)")  // "Home"

print((0..<tabs.count).map { tabs.at($0).name })  // ["home-tab", "settings-tab"]
```

> See `spec/06-composite-vm.md` for the full `CompositeVM` contract.

______________________________________________________________________

## 6. Lifecycle and cleanup

Every VM follows a five-state lifecycle:
`destructed → constructing → constructed → destructing → destructed`,
plus the terminal `disposed`.

```swift
print(userVM.status)            // ConstructionStatus.constructed

try userVM.reconstruct()            // destruct + construct in one call — only valid
                                // from .constructed; round-trips back to it
print(userVM.status)            // ConstructionStatus.constructed

try userVM.destruct()
print(userVM.status)            // ConstructionStatus.destructed

userVM.dispose()                // idempotent + terminal
print(userVM.status)            // ConstructionStatus.disposed

tabs.dispose()                  // disposes children, then itself
hub.dispose()
```

An illegal transition (e.g. calling `construct()` on a disposed VM) surfaces a
**catchable** `StatusTransitionError` under the v3 lifecycle convergence
(ADR-0053) — `construct()` / `destruct()` / `reconstruct()` are `throws` (hence
the `try` above), so wrap them in `do`/`catch`, or gate with `canConstruct()` /
`canDestruct()` if a state is uncertain. (Swift still **traps** only where a
setter cannot throw — e.g. assigning a non-child to `CompositeVM.current`; see
ADR-0009/ADR-0037.) A `BuilderValidationError` is likewise thrown when a builder
is missing a required field at `build()` time.

> See `spec/02-lifecycle.md` for the full transition table (LIFE-001..014).

______________________________________________________________________

## 7. Threading

`Dispatcher` is a closure-routing protocol — not a Combine `Scheduler`. It
exposes two scheduling sinks that the rest of VMx uses when it needs to
hop work between queues:

| Method                                  | Default mapping (`DefaultDispatcher`)          |
| --------------------------------------- | ---------------------------------------------- |
| `dispatcher.scheduleForeground { ... }` | `DispatchQueue.main` (sync if already on main) |
| `dispatcher.scheduleBackground { ... }` | `DispatchQueue.global(qos: .userInitiated)`    |

Use it for imperative marshaling — e.g., load data on a background queue
then apply the result on main:

```swift
dispatcher.scheduleBackground {
    let data = loadFromDatabase()
    dispatcher.scheduleForeground {
        userVM.model = data
        userVM.construct()
    }
}
```

For Combine subscriptions on `hub.messages`, marshal to the main queue
with Combine's own `.receive(on:)` — `DispatchQueue.main` is the
idiomatic Scheduler for SwiftUI / UIKit binding:

```swift
import Combine
import VMx

let cancellable = hub.messages
    .compactMap { $0 as? PropertyChangedMessage }
    .receive(on: DispatchQueue.main)           // marshal to the main queue
    .sink { msg in
        // updateLabel(msg) — safe to touch UIKit / SwiftUI state here
    }
```

> See `spec/11-threading.md` for the `THR-001..THR-004` conformance rules.
> The Swift flavor implements the dispatcher contract; the Combine /
> async-await integration patterns above are flavor-idiomatic.

______________________________________________________________________

## 8. Where to go next

| Resource                      | Path                          |
| ----------------------------- | ----------------------------- |
| Spec overview                 | `spec/00-overview.md`         |
| Lifecycle contract            | `spec/02-lifecycle.md`        |
| Message schema                | `spec/03-messages.md`         |
| Commands                      | `spec/04-commands.md`         |
| ComponentVM contract          | `spec/05-component-vm.md`     |
| CompositeVM contract          | `spec/06-composite-vm.md`     |
| Builder spec                  | `spec/10-builders.md`         |
| Threading rules               | `spec/11-threading.md`        |
| Architecture decision records | `spec/ADRs/`                  |
| SwiftUI integration recipe    | `docs/integration/swiftui.md` |
| Swift flavor README           | `langs/swift/README.md`       |
| Swift conformance suite       | `langs/swift/Tests/VMxTests/` |
