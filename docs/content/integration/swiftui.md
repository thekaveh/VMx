# 9.12. SwiftUI Integration

Wire a `ComponentVMOf<Model>` to a SwiftUI view using `@StateObject` /
`@ObservedObject` plus a tiny Combine adapter that bridges the VMx
message hub into SwiftUI's `ObservableObject` machinery.

## 9.12.1. Reactivity primitive

SwiftUI re-renders when an `ObservableObject` publishes through its
`objectWillChange` publisher. VMx VMs publish `PropertyChangedMessage`
to their hub and emit a string-keyed `propertyChanged` Combine
publisher. The adapter forwards every relevant event into
`objectWillChange.send()`.

## 9.12.2. Mapping

| SwiftUI                            | VMx                                       |
| ---------------------------------- | ----------------------------------------- |
| `@StateObject` / `@ObservedObject` | wrapper around a `ComponentVMOf<M>`       |
| `objectWillChange.send()`          | hub `PropertyChangedMessage` subscription |
| `Button(action: …)`                | `command.execute()`                       |
| `.onDisappear { … }`               | cancel subscriptions / dispose VM         |

## 9.12.3. Adapter skeleton

```swift
import SwiftUI
import Combine
import VMx

final class TabAdapter<M>: ObservableObject {
    let vm: ComponentVMOf<M>
    private var cancellables: Set<AnyCancellable> = []

    init(_ vm: ComponentVMOf<M>) {
        self.vm = vm
        vm.propertyChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }
}

struct TabContentView: View {
    @StateObject var adapter: TabAdapter<TabModel>

    var body: some View {
        VStack {
            Text(adapter.vm.model.title)
            Button("Save") { adapter.vm.selectCommand.execute() }
        }
        // `construct()` is throwing as of ADR-0053 (see §4). A legal
        // transition is the common path; `try?` discards the recoverable
        // `StatusTransitionError` an illegal/in-flight transition would throw.
        .onAppear { try? adapter.vm.construct() }
        .onDisappear { adapter.vm.dispose() }
    }
}
```

## 9.12.4. Lifecycle is throwing (ADR-0053)

As of the v3 convergence (ADR-0053, superseding ADR-0037 §2.5), the Swift
lifecycle operations `construct()`, `destruct()`, and `reconstruct()` are
`throws` — matching the catchable exceptions the C#/Python/TypeScript flavors
already raise, instead of the earlier uncatchable `preconditionFailure` trap.
An **illegal transition** (e.g. `construct()` on a disposed VM) or a concurrent
re-invocation while a transition is in flight throws a catchable
`StatusTransitionError`; the legal idempotent no-ops (`construct` from
`Constructed`, `destruct` from `Destructed`) still return without throwing.

```swift
do {
    try adapter.vm.construct()
} catch let error as StatusTransitionError {
    // Recover — the VM is left in its prior settled state, not crashed.
    print("illegal lifecycle transition: \(error)")
}
```

A non-child `current` assignment likewise has a throwing companion
(`setCurrent(_:) throws`, throwing `CompositeMembershipError`); see ADR-0053 §2.2.

## 9.12.5. Fuller example

The SwiftUI Notes Workspace flagship lives at
[`examples/swift/notes-showcase/`](../../examples/swift/notes-showcase/). Its
`NotesShowcaseCore` target keeps the pure VM layer separate from SwiftUI, while
the app target contains the Combine-to-SwiftUI binding bridge.

## 9.12.6. Cross-flavor parity

This recipe parallels the React adapter ([react.md](react.md)) — both
bridge a hub message stream into the framework's "re-render this view"
hook. The Avalonia ([avalonia.md](avalonia.md)) and Textual
([textual.md](textual.md)) recipes follow the same shape.
