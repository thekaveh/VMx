# 7.5. Swift

## Snapshot

- Install: add the `langs/swift` package through SwiftPM
- Publication status: consumed from repo tags after a `swift-v*` release
  publishes it.
- Reactive primitive: `Combine`
- Naming idiom: camelCase

## What To Reach For

Swift is the right fit when you want the same VMx lifecycle and conformance
surface in a SwiftPM package, with SwiftUI adapters kept outside the core
library boundary.

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
