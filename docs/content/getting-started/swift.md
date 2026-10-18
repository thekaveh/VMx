# 3.5. Getting Started with VMx — Swift

This tutorial walks you through building viewmodels with the VMx Swift
package. You will build a `ComponentVMOf<UserModel>`, a `RelayCommand`, and a
`CompositeVM<TabVM>` with tab selection — all in a Swift Package or playground.

> The Swift source line 3.30.0 covers all 425 library conformance IDs. The
> SwiftUI Notes Workspace flagship covers the 5 `THEME-00x` scenario IDs. The
> [Swift flavor](../flavors/swift.md) page lists the documented Swift-specific
> divergences.
>
> For the contracts behind each type, see the [component
> family](../primitives/viewmodel-families/component-family.md), [command
> families](../primitives/command-families.md), and [composite
> family](../primitives/viewmodel-families/composite-family.md).

______________________________________________________________________

## 3.5.1. Install

Add VMx as described in [Installation](../installation.md). The SwiftPM tag
3.24.0 implements spec 3.23.x. Behavior from later spec versions needs the
source checkout, added as a path dependency. The package uses Combine and
Dispatch and has no third-party dependencies.

______________________________________________________________________

## 3.5.2. Wire up `MessageHub` and a `Dispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your scheduler pair.

### 3.5.2.1. Option A — immediate (test suites / synchronous scripts)

```swift
import VMx

let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE
// Both foreground and background run synchronously on the calling thread.
// Safe for XCTest suites with no async event loop.
```

### 3.5.2.2. Option B — default (SwiftUI / UIKit / AppKit apps)

```swift
import VMx

let hub = MessageHub()
let dispatcher = DefaultDispatcher()
// foreground → DispatchQueue.main
// background → DispatchQueue.global(qos: .userInitiated)
```

______________________________________________________________________

## 3.5.3. Build a `ComponentVMOf<UserModel>`

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

> See the [component family](../primitives/viewmodel-families/component-family.md)
> for the full component contract.

______________________________________________________________________

## 3.5.4. Build a `RelayCommand`

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

> See [command families](../primitives/command-families.md) for the full command
> contract.

______________________________________________________________________

## 3.5.5. Build a `CompositeVM<TabVM>`

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
print(tabs.current?.model.title ?? "(none)")  // Settings

tabs.current = tab1
print(tabs.current?.model.title ?? "(none)")  // Home

print((0..<tabs.count).compactMap { tabs.at($0).name })  // ["home-tab", "settings-tab"]
```

> See the [composite family](../primitives/viewmodel-families/composite-family.md)
> for the full `CompositeVM` contract.

______________________________________________________________________

## 3.5.6. Lifecycle and cleanup

Every VM has five lifecycle states. Four of them form a reversible cycle,
`destructed → constructing → constructed → destructing → destructed`. The fifth
state, `disposed`, is terminal.

```swift
print(userVM.status)            // constructed

try userVM.reconstruct()        // destruct + construct in one call; only valid
                                // from .constructed, and returns to it
print(userVM.status)            // constructed

try userVM.destruct()
print(userVM.status)            // destructed

userVM.dispose()                // idempotent + terminal
print(userVM.status)            // disposed

tabs.dispose()                  // disposes children, then itself
```

Dispose the hub last, after every viewmodel that uses it. The threading
examples below still use the hub, so the full shutdown sequence appears at the
end of section 3.5.7.

An illegal transition, such as `construct()` on a disposed VM, throws a
catchable `StatusTransitionError`. The `construct()`, `destruct()`, and
`reconstruct()` methods are `throws`, so call them with `try` inside
`do`/`catch`. If the state is uncertain, check `canConstruct()` or
`canDestruct()` first.

Swift traps only where a setter cannot throw (ADR-0009, ADR-0037). For example,
assigning a non-child to the `CompositeVM.current` setter traps. Call
`setCurrent(_:)` instead: it throws a catchable `CompositeMembershipError` for
a non-child. A builder throws `BuilderValidationError` from `build()` when a
required field is missing.

> See [Lifecycle & Messaging](../architecture/lifecycle-messaging.md) for the
> full lifecycle contract (`LIFE-001..015`),
> including the transition table and admitted-hook/disposal coordination.

______________________________________________________________________

## 3.5.7. Threading

`Dispatcher` is a closure-routing protocol — not a Combine `Scheduler`. It
exposes two scheduling sinks that the rest of VMx uses when it needs to
hop work between queues:

| Method                                  | Default mapping (`DefaultDispatcher`)          |
| --------------------------------------- | ---------------------------------------------- |
| `dispatcher.scheduleForeground { ... }` | `DispatchQueue.main` (sync if already on main) |
| `dispatcher.scheduleBackground { ... }` | `DispatchQueue.global(qos: .userInitiated)`    |

Use it for imperative marshaling. For example, load data on a background
queue, then apply the result on main. This example builds a new viewmodel
because section 3.5.6 disposed `userVM`.

```swift
let profileVM = try ComponentVMOf<UserModel>.builder()
    .name("profile")
    .model(UserModel(name: "", email: ""))
    .services(hub: hub, dispatcher: dispatcher)
    .build()

dispatcher.scheduleBackground {
    let data = loadFromDatabase()
    dispatcher.scheduleForeground {
        profileVM.model = data
        // scheduleForeground takes a non-throwing closure; handle the error here.
        do {
            try profileVM.construct()
        } catch {
            print("construct failed: \(error)")
        }
    }
}
```

For Combine subscriptions on `hub.messages`, marshal to the main queue
with Combine's own `.receive(on:)` — `DispatchQueue.main` is the
idiomatic Scheduler for SwiftUI / UIKit binding:

```swift
import Combine
import Foundation
import VMx

let cancellable = hub.messages
    .compactMap { $0 as? PropertyChangedMessage }
    .receive(on: DispatchQueue.main)           // marshal to the main queue
    .sink { msg in
        // updateLabel(msg) — safe to touch UIKit / SwiftUI state here
    }
```

At shutdown, cancel subscriptions, then dispose the viewmodels and the hub last:

```swift
cancellable.cancel()
profileVM.dispose()
hub.dispose()
```

> See [Services, Messages &
> Dispatching](../primitives/services-messages-dispatching.md) for the
> `THR-001..THR-004` conformance rules.
> The Swift flavor implements the dispatcher contract; the Combine /
> async-await integration patterns above are flavor-idiomatic.

______________________________________________________________________

## 3.5.8. Where to go next

| Resource             | Documentation page                                                                             |
| -------------------- | ---------------------------------------------------------------------------------------------- |
| Specification status | [Specification & Conformance](../specification-conformance.md)                                 |
| Lifecycle contract   | [Lifecycle & Messaging](../architecture/lifecycle-messaging.md)                                |
| Messages & threading | [Services, Messages & Dispatching](../primitives/services-messages-dispatching.md)             |
| Commands             | [Command Families](../primitives/command-families.md)                                          |
| Component contract   | [Component Family](../primitives/viewmodel-families/component-family.md)                       |
| Composite contract   | [Composite Family](../primitives/viewmodel-families/composite-family.md)                       |
| Builders & tree      | [Builders, Collections & Tree Utilities](../primitives/builders-collections-tree-utilities.md) |
| Architecture         | [Architecture Map](../architecture/index.md)                                                   |
| Swift status         | [Swift Flavor](../flavors/swift.md)                                                            |
| SwiftUI integration  | [SwiftUI Integration](../integration/swiftui.md)                                               |
