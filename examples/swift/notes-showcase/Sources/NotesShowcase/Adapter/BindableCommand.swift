//
// BindableCommand — Combine → SwiftUI bridge for a VMx Command.
//
// Subscribes to `command.canExecuteChanged` and mirrors the current
// `canExecute()` result as `@Published var canExecute`, so SwiftUI
// button `.disabled(!cmd.canExecute)` reacts to predicate changes.
//
import Combine
import SwiftUI
import VMx

/// Combine → SwiftUI bridge for a VMx `Command`.
///
/// Hold as `@StateObject` or `@ObservedObject`. Call `execute()` from
/// button actions; bind `.disabled(!cmd.canExecute)` to gate the button.
final class BindableCommand: ObservableObject {
    /// Current `canExecute()` result — updated on the main run loop.
    @Published var canExecute: Bool
    /// Invokes the wrapped command (no-ops when `canExecute` is false,
    /// matching `RelayCommand`'s own gate).
    let execute: () -> Void
    private var cancellable: AnyCancellable?

    init(_ command: any Command) {
        canExecute = command.canExecute()
        execute = { command.execute() }
        cancellable = command.canExecuteChanged
            .receive(on: RunLoop.main)
            .sink { [weak self] in
                self?.canExecute = command.canExecute()
            }
    }
}
