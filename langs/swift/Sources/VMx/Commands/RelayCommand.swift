//
// RelayCommand — concrete `Command` backed by a predicate + task closure.
//
// See spec/04-commands.md.
//
// Behavior contract (mirrors the other flavors):
// - Predicate nil → `canExecute()` returns true unconditionally.
// - Task nil → `execute()` is a no-op (no error raised).
// - `execute()` is gated on `canExecute()`: if false, returns immediately.
// - Predicate that throws → treated as false (does NOT propagate).
// - Task that throws → propagates to the caller of `execute()`.
//   (Swift closures must declare `throws`; this flavor uses non-throwing
//   closures for parity with TS/Python — host code should catch internally.)
// - Trigger emissions fire `canExecuteChanged`.
// - `raiseCanExecuteChanged()` emits one imperative re-evaluation notification.
// - Disposed commands are inert: `canExecute()` returns false and `execute()` is a no-op.
// - Builder is immutable: every setter returns a new builder instance.
// - Triggers are additive across `.triggers(...)` calls.
//
import Foundation
import Combine

public final class RelayCommand: Command {
    private let task: (() -> Void)?
    private let predicate: (() -> Bool)?
    private let canExecuteChangedSubject = PassthroughSubject<Void, Never>()
    private var cancellables: Set<AnyCancellable> = []
    private var disposed = false

    public init(
        task: (() -> Void)?,
        predicate: (() -> Bool)?,
        triggers: [AnyPublisher<Void, Never>]
    ) {
        self.task = task
        self.predicate = predicate

        let subject = canExecuteChangedSubject
        for trigger in triggers {
            trigger
                .sink { _ in subject.send(()) }
                .store(in: &cancellables)
        }
    }

    public func canExecute() -> Bool {
        guard !disposed else { return false }
        guard let predicate else { return true }
        // Swift closures can't "throw and be treated as false" without an
        // explicit `throws` signature; this matches the other flavors'
        // behavior at the level of "predicate returned false".
        return predicate()
    }

    public func execute() {
        guard canExecute() else { return }
        task?()
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        canExecuteChangedSubject.eraseToAnyPublisher()
    }

    /// Emits one re-evaluation notification without invoking user closures.
    /// Repeated calls are additive; calls after disposal are no-ops.
    public func raiseCanExecuteChanged() {
        guard !disposed else { return }
        canExecuteChangedSubject.send(())
    }

    /// Idempotent. Subsequent calls are a no-op.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        canExecuteChangedSubject.send(())
        cancellables.removeAll()
        canExecuteChangedSubject.send(completion: .finished)
    }

    /// Entrypoint for the immutable builder.
    public static func builder() -> RelayCommandBuilder {
        RelayCommandBuilder()
    }
}
