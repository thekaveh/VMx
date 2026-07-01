//
// BindableVM — Combine → SwiftUI property bridge for ComponentVMBase.
//
// Scenario §7.1 (PropertyBridge): subscribes once to `vm.propertyChanged`
// and calls `objectWillChange.send()` on the main run loop on each emission,
// driving SwiftUI re-renders. Views read live values directly from `vm`'s
// getters (whole-VM-subscription pattern, scenario §7.2).
//
// Thread safety: `.receive(on: RunLoop.main)` ensures every objectWillChange
// emission happens on the UI thread regardless of which thread the VM
// publishes on.
//
import Combine
import SwiftUI
import VMx

/// Combine → SwiftUI bridge for any `ComponentVMBase`.
///
/// Hold as `@StateObject` in the owning view; pass the underlying `vm`
/// reference to child views that only need to read from it.
final class BindableVM<VM: ComponentVMBase>: ObservableObject {
    /// The wrapped VM — read live getters from here after each re-render.
    let vm: VM
    private var cancellable: AnyCancellable?

    init(_ vm: VM) {
        self.vm = vm
        cancellable = vm.propertyChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.objectWillChange.send()
            }
    }
}
