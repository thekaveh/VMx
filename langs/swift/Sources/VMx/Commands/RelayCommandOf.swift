//
// RelayCommandOf<T> — parameterized concrete command backed by a predicate + task closure.
//
// See spec/04-commands.md.
//
// Behavior contract (mirrors the other flavors and RelayCommand):
// - Predicate nil → `canExecute(_:)` returns true unconditionally.
// - Task nil → `execute(_:)` is a no-op (no error raised).
// - `execute(_:)` is gated on `canExecute(_:)`: if false, returns immediately.
// - Trigger emissions fire `canExecuteChanged`.
// - Disposed commands are inert: `canExecute(_:)` returns false and `execute(_:)` is a no-op.
// - Builder is immutable: every setter returns a new builder instance.
// - Triggers are additive across `.triggers(...)` calls.
//
import Foundation
import Combine

public final class RelayCommandOf<T> {
    private let task: ((T) -> Void)?
    private let predicate: ((T) -> Bool)?
    private let canExecuteChangedSubject = PassthroughSubject<Void, Never>()
    private var cancellables: Set<AnyCancellable> = []
    private var disposed = false

    public init(
        task: ((T) -> Void)?,
        predicate: ((T) -> Bool)?,
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

    public func canExecute(_ parameter: T) -> Bool {
        guard !disposed else { return false }
        guard let predicate else { return true }
        return predicate(parameter)
    }

    public func execute(_ parameter: T) {
        guard canExecute(parameter) else { return }
        task?(parameter)
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        canExecuteChangedSubject.eraseToAnyPublisher()
    }

    /// Idempotent. Subsequent calls are a no-op.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        // Terminal "re-evaluate — now disabled" nudge before completion, matching
        // RelayCommand + the C#/Python/TypeScript relay commands (7 of 8 sync relay
        // dispose paths emit this; this variant was the lone omission).
        canExecuteChangedSubject.send(())
        cancellables.removeAll()
        canExecuteChangedSubject.send(completion: .finished)
    }

    /// Entrypoint for the immutable builder.
    public static func builder() -> RelayCommandOfBuilder<T> {
        RelayCommandOfBuilder()
    }
}
