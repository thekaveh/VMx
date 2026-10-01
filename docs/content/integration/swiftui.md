# 9.12. SwiftUI Integration

Wire a `ComponentVMOf<Model>` to a SwiftUI view with a small Combine adapter
that bridges VMx change notifications into SwiftUI's `ObservableObject`
machinery. The adapter decides who owns the VM's lifetime; appearing and
disappearing never end it.

## 9.12.1. Reactivity primitive

SwiftUI re-renders when an `ObservableObject` publishes through its
`objectWillChange` publisher. VMx VMs publish `PropertyChangedMessage`
to their hub and emit a string-keyed `propertyChanged` Combine
publisher. The adapter forwards every relevant event into
`objectWillChange.send()`.

## 9.12.2. Mapping

| SwiftUI                     | VMx                                                           |
| --------------------------- | ------------------------------------------------------------- |
| `@StateObject` adapter      | `ObservableObject` wrapper around a `ComponentVMOf<M>`        |
| `objectWillChange.send()`   | `propertyChanged` subscription                                |
| `Button(action: …)`         | the domain command's `execute()`, for example a save command  |
| `.onAppear { … }`           | construct an owned VM once; repeated appearances are no-ops   |
| `.onDisappear { … }`        | nothing terminal: the view may appear again                   |
| adapter released by SwiftUI | dispose an owned VM exactly once; never dispose a borrowed VM |

Disposal is terminal: a disposed VM cannot be constructed again, so tying
`dispose()` to `.onDisappear` breaks any view that reappears (tabs, navigation
stacks, lazy lists). Choose an ownership policy instead:

- **Owned**: the view created the VM. The adapter constructs it on first
  appearance and disposes it once when SwiftUI releases the `@StateObject`.
- **Borrowed**: a parent VM or app state owns the VM, as the
  [Notes Workspace](../../../examples/swift/notes-showcase/) keeps its
  `WorkspaceVM` for the window's lifetime. The view only observes it.

## 9.12.3. Adapter and view

This is the exact code compiled and exercised by
`langs/swift/Tests/VMxTests/SwiftUIRecipeTests.swift`: appear, disappear, and
appear again; owned versus borrowed cleanup; Save; and a surfaced construction
failure.

<!-- checked-snippet: langs/swift/Tests/VMxTests/SwiftUIRecipeTests.swift#swiftui-recipe -->

```swift
import Combine
import SwiftUI
import VMx

struct Note: Equatable {
    var title: String
}

/// Who ends the view model's lifetime.
enum ViewModelOwnership {
    /// The view created the VM: construct it on first appearance and dispose
    /// it exactly once, when SwiftUI releases the adapter.
    case owned
    /// A parent owns the VM: the view observes it and never changes its
    /// lifecycle.
    case borrowed
}

/// Bridges a VMx view model into SwiftUI. Appearance never ends the VM's
/// lifetime, because a view that disappears may appear again.
final class ViewModelAdapter<Model>: ObservableObject {
    let vm: ComponentVMOf<Model>
    let ownership: ViewModelOwnership
    /// A lifecycle failure for the host to show; never swallowed.
    @Published private(set) var lifecycleError: (any Error)?
    private var cancellables: Set<AnyCancellable> = []

    init(_ vm: ComponentVMOf<Model>, ownership: ViewModelOwnership) {
        self.vm = vm
        self.ownership = ownership
        vm.propertyChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }

    /// Call from `.onAppear`. Constructing an already constructed VM is a
    /// no-op, so repeated appearances are safe.
    func appeared() {
        guard ownership == .owned, lifecycleError == nil else { return }
        do {
            try vm.construct()
        } catch {
            lifecycleError = error
        }
    }

    deinit {
        cancellables.removeAll()
        if ownership == .owned {
            vm.dispose()
        }
    }
}

struct NoteView: View {
    @StateObject private var adapter: ViewModelAdapter<Note>
    private let save: any Command

    /// `save` is the domain's save command, e.g. from a form or workspace VM.
    init(vm: ComponentVMOf<Note>, ownership: ViewModelOwnership, save: any Command) {
        _adapter = StateObject(wrappedValue: ViewModelAdapter(vm, ownership: ownership))
        self.save = save
    }

    var body: some View {
        VStack {
            if let error = adapter.lifecycleError {
                Text("Could not open this note: \(String(describing: error))")
            }
            Text(adapter.vm.model.title)
            Button("Save") { save.execute() }
                .disabled(!save.canExecute())
        }
        .onAppear { adapter.appeared() }
    }
}
```

The Save button runs the command it is given, typically the save or approve
command of a form or workspace VM. A component's `selectCommand` only selects it
in its parent; it persists nothing.

Construction errors are not discarded with `try?`: the adapter stores them in
`lifecycleError` so the host can show them, and later cleanup cannot mask them.

## 9.12.4. Lifecycle is throwing (ADR-0053)

As of the v3 convergence (ADR-0053, superseding ADR-0037 §2.5), the Swift
lifecycle operations `construct()`, `destruct()`, and `reconstruct()` are
`throws` — matching the catchable exceptions the C#/Python/TypeScript flavors
already raise, instead of the earlier uncatchable `preconditionFailure` trap.
An **illegal transition** (e.g. `construct()` on a disposed VM) or a concurrent
re-invocation while a transition is in flight throws a catchable
`StatusTransitionError`; the legal idempotent no-ops (`construct` from
`Constructed`, `destruct` from `Destructed`) still return without throwing.

<!-- checked-snippet: langs/swift/Tests/VMxTests/SwiftUIRecipeTests.swift#swiftui-throwing-lifecycle -->

```swift
do {
    try vm.construct()
} catch let error as StatusTransitionError {
    // Recover — the VM is left in its prior settled state, not crashed.
    print("illegal lifecycle transition: \(error)")
}
```

A non-child `current` assignment likewise has a throwing companion
(`setCurrent(_:) throws`, throwing `CompositeMembershipError`); see ADR-0053 §2.2.

## 9.12.5. Fuller example

The SwiftUI Notes Workspace flagship lives at
[`examples/swift/notes-showcase/`](../../../examples/swift/notes-showcase/). Its
`NotesShowcaseCore` target keeps the pure VM layer separate from SwiftUI, while
the app target contains the Combine-to-SwiftUI binding bridge.

## 9.12.6. Cross-flavor parity

This recipe parallels the React adapter ([react.md](react.md)) — both
bridge a hub message stream into the framework's "re-render this view"
hook. The Avalonia ([avalonia.md](avalonia.md)) and Textual
([textual.md](textual.md)) recipes follow the same shape.
