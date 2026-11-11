# 7.5. Swift

## 7.5.1. Snapshot

- Current source: Swift 4.0.0 implementing spec 3.30.0
- Install and package status: see [Installation](../installation.md) and
  [Availability](../index.md#11-availability).
- Reactive primitive: `Combine`. `FormVM` channels and the `canExecuteChanged`
  of its commands call sinks without a delivery lock (ADR-0174), as C# and
  Python do, so one sink can run on two threads at once.
- Naming idiom: camelCase
- Hub delivery and notification replay: see
  [Callback-Safe Transition Ordering](../architecture/lifecycle-messaging.md#542-callback-safe-transition-ordering)

## 7.5.2. What To Reach For

Swift is the right fit when you want the same VMx lifecycle and conformance
surface in a SwiftPM package, with SwiftUI adapters kept outside the core
library boundary.

Use `.product(name: "VMx", package: "vmx")` in the consuming target. The
lowercase package value is SwiftPM's canonical identity for the repository;
the imported module and product remain `VMx`.

`VMx.Notification` has the same name as `Foundation.Notification`. In a file
that imports both modules, the unqualified `Notification` in a type position
fails with `'Notification' is ambiguous for type lookup in this context`.
Write `VMx.Notification`, or declare a type alias:

```swift
import Foundation
import VMx

typealias VMxNotification = VMx.Notification

func messages(of pending: [VMxNotification]) -> [String] {
    pending.map(\.message)
}
```

## 7.5.3. Serviced Collections

`ServicedObservableCollection<T>` publishes locally through Combine, then to
an optional external hub:

```swift
let notes = ServicedObservableCollection<Note>(hub: hub)
let changes = notes.collectionChanged.sink { message in render(message) }

notes.append(first)
notes.append(second)
notes.replace(at: 0, with: revised)  // setAt remains available
try notes.move(from: 0, to: notes.count - 1)
notes.replaceAll(serverSnapshot)     // one Reset
```

Value removal is available when `T: Equatable`. `removeAt` and `replace` keep
Swift's array-precondition bounds behavior; `move` instead throws the catchable
`VMCollectionIndexError`. Messages expose `index`, `oldIndex`, and `newIndex`.
The caller owns the Combine cancellable. The
[Serviced Mutation Contract](../primitives/builders-collections-tree-utilities.md#677-serviced-mutation-contract)
gives the shared rules for no-op cases, value removal, delivery order, and item
ownership.

Use `ObservableList<T>` for batching and `Count` notifications.

Use `KeyedServicedObservableCollection<Key,T>` for captured-key access while
retaining the same ordered message contract:

```swift
let notesByID = KeyedServicedObservableCollection<String, Note>(
    keyOf: { $0.id },
    hub: hub
)
try notesByID.append(first)
let note = notesByID.get(first.id)
let added = try notesByID.upsert(revised) // false: Replace at stable position
let removed = notesByID.delete(first.id)
```

`containsKey` tests membership. The projector is throwing, so append,
replacement, whole-list replacement, and upsert are throwing and atomic.

Mutating `id` does not rekey the membership. The
[Keyed Serviced Mutation Contract](../primitives/builders-collections-tree-utilities.md#678-keyed-serviced-mutation-contract)
gives the shared rules for captured keys, atomic failures, costs, and hub
delivery.

## 7.5.4. Imperative Engine Bridge

The `Equatable` overload of `subscribeValue` uses `==`; the `isEqual:` overload
accepts custom equality without an `Equatable` constraint. Both return
`AnyCancellable`:

```swift
import Combine
import VMx

let exposureSubscription: AnyCancellable = try subscribeValue(
    cameraVM,
    selector: { $0.model.exposure },
    callback: { exposure, _ in
        material.uniforms.exposure.value = exposure
    },
    fireImmediately: true
)

// Host adapter disposal:
exposureSubscription.cancel()
```

The
[Imperative Selected-State Bridge](../primitives/services-messages-dispatching.md#666-imperative-selected-state-bridge)
gives the shared callback, reevaluation, and ownership rules.

## 7.5.5. Pointers

- Flavor README:
  [langs/swift/README.md](../../../langs/swift/README.md)
- Getting started guide:
  [Getting Started with VMx — Swift](../getting-started/swift.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- SwiftUI recipe:
  [SwiftUI Integration](../integration/swiftui.md)

## 7.5.6. Current Example Coverage

- SwiftUI flagship: `examples/swift/notes-showcase/`

The Swift flavor is at full library parity. Its current example surface is
narrower than the other languages, but the flagship README points to the same
cross-flavor scenario contract and parity matrix.

## 7.5.7. Coverage

CI gates Swift library coverage; see
[Coverage Floors](../contributing-releases.md#1133-coverage-floors).
