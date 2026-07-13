# 7.5. Swift

## Snapshot

- Install: `.package(url: "https://github.com/thekaveh/VMx.git", from: "3.20.0")`
- Publication status: 3.20.0 is public through the immutable `v3.20.0`
  SwiftPM tag and matching `swift-v3.20.0` GitHub Release.
- Reactive primitive: `Combine`
- Naming idiom: camelCase

## What To Reach For

Swift is the right fit when you want the same VMx lifecycle and conformance
surface in a SwiftPM package, with SwiftUI adapters kept outside the core
library boundary.

Use `.product(name: "VMx", package: "vmx")` in the consuming target. The
lowercase package value is SwiftPM's canonical identity for the repository;
the imported module and product remain `VMx`.

## Serviced Collections

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

Value removal is available when `T: Equatable`, removes the first match, and
returns `false` when absent. `removeAt` and `replace` retain Swift's established
array-precondition bounds behavior; `move` instead throws the catchable
`VMCollectionIndexError`. Equal-index move and empty clear are no-ops. The
caller owns both the Combine cancellable and every stored item.

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
Captured membership keys do not follow mutable properties; indexed replacement
or delete-then-add rekeys explicitly. The same mutated instance can occupy its
old and newly projected memberships. Duplicate/projector failure preserves
state and emits nothing. Lookup and target discovery are expected O(1), append
is amortized O(1), and ordered middle shifts remain O(n). Local Combine
delivery stays immediate when an external hub transaction defers only hub
publication. Items remain caller-owned; the keyed type adds no batch or VM
lifecycle interface.

## Imperative Engine Bridge

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

The callback receives `(current, previous)`; immediate delivery uses the
initial value for both. The host adapter owns the cancellable, and the selector
reevaluates after every property message from this fixed VM rather than on
every render frame.

## Pointers

- Flavor README:
  [langs/swift/README.md](../../../langs/swift/README.md)
- Getting started guide:
  [docs/getting-started/swift.md](../../getting-started/swift.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- SwiftUI recipe:
  [docs/integration/swiftui.md](../../integration/swiftui.md)

## Current Example Coverage

- SwiftUI flagship: `examples/swift/notes-showcase/`

The Swift flavor is at full library parity. Its current example surface is
narrower than the other languages, but the flagship README points to the same
cross-flavor scenario contract and parity matrix.
