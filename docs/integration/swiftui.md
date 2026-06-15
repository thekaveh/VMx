# SwiftUI integration

Wire a `ComponentVMOf<Model>` to a SwiftUI view using `@StateObject` /
`@ObservedObject` plus a tiny Combine adapter that bridges the VMx
message hub into SwiftUI's `ObservableObject` machinery.

## 1. Reactivity primitive

SwiftUI re-renders when an `ObservableObject` publishes through its
`objectWillChange` publisher. VMx VMs publish `PropertyChangedMessage`
to their hub and emit a string-keyed `propertyChanged` Combine
publisher. The adapter forwards every relevant event into
`objectWillChange.send()`.

## 2. Mapping

| SwiftUI                            | VMx                                       |
| ---------------------------------- | ----------------------------------------- |
| `@StateObject` / `@ObservedObject` | wrapper around a `ComponentVMOf<M>`       |
| `objectWillChange.send()`          | hub `PropertyChangedMessage` subscription |
| `Button(action: …)`                | `command.execute()`                       |
| `.onDisappear { … }`               | cancel subscriptions / dispose VM         |

## 3. Adapter skeleton

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

struct TabView: View {
    @StateObject var adapter: TabAdapter<TabModel>

    var body: some View {
        VStack {
            Text(adapter.vm.model.title)
            Button("Save") { adapter.vm.selectCommand.execute() }
        }
        .onDisappear { adapter.vm.dispose() }
    }
}
```

## 4. Fuller example

The Swift flavor's first release does not yet ship a Notes-Showcase
SwiftUI app; the [`langs/swift/README.md`](../../langs/swift/README.md)
covers the broader install + quick-start flow. A SwiftUI flagship is
planned for the follow-up PR.

## 5. Cross-flavor parity

This recipe parallels the React adapter ([react.md](react.md)) — both
bridge a hub message stream into the framework's "re-render this view"
hook. The Avalonia ([avalonia.md](avalonia.md)) and Textual
([textual.md](textual.md)) recipes follow the same shape.
