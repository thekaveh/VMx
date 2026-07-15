//
// ConfirmationDecoratorCommand — gates execution on an async confirm delegate.
//
// See spec/04-commands.md §8.3 and ADR-0049.
//
// Behaviour:
// - canExecute() delegates verbatim to inner.canExecute() (CMDD-008).
// - execute() is fire-and-forget: launches a Swift Task that awaits the confirm
//   gate and runs inner.execute() only when it returns true (CMDD-007).
//   Any error thrown by the confirm closure is routed to the `errors` channel
//   instead of being swallowed (CMDD-010).
// - executeAsync() is the awaitable path: gates on canExecute → awaits confirm
//   → runs inner if true; rethrows inline.
// - errors: AnyPublisher<Error, Never> backed by a PassthroughSubject that is
//   completed on dispose() (Combine; mirrors rxjs Subject in TS flavour).
// - canExecuteChanged delegates to inner.
// - dispose() completes the errors subject; idempotent.
//
// Note: Command.execute() is non-throwing in the Swift protocol surface, so a
// "throwing inner" in the TS sense maps here to the confirm closure throwing.
// The confirm parameter is therefore typed `() async throws -> Bool` so that
// CMDD-010's throwing-confirm scenario is directly testable.
//
import Foundation
import Combine

public final class ConfirmationDecoratorCommand: Command {
    private let inner: Command
    private let confirm: () async throws -> Bool
    private let errorsSubject = PassthroughSubject<Error, Never>()
    private var disposed = false

    public init(_ inner: Command, confirm: @escaping () async throws -> Bool) {
        self.inner = inner
        self.confirm = confirm
    }

    // MARK: - Command

    public func canExecute() -> Bool {
        inner.canExecute()
    }

    /// Fire-and-forget. Errors from the confirm gate are routed to `errors`
    /// rather than propagated to the synchronous caller (CMDD-010).
    public func execute() {
        let command = UncheckedSendableBox(self)
        Task { [command] in
            do {
                try await command.value.executeAsync()
            } catch {
                command.value.errorsSubject.send(error)
            }
        }
    }

    /// Awaitable path — gates on canExecute, awaits confirm, runs inner when
    /// true. Rethrows inline so the caller can observe confirm errors directly.
    public func executeAsync() async throws {
        guard canExecute() else { return }
        let ok = try await confirm()
        if ok { inner.execute() }
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        inner.canExecuteChanged
    }

    // MARK: - Errors channel

    /// Observable that surfaces errors from the fire-and-forget `execute()` path
    /// (e.g. a throwing confirm delegate). Completes on `dispose()` (CMDD-010).
    public var errors: AnyPublisher<Error, Never> {
        errorsSubject.eraseToAnyPublisher()
    }

    // MARK: - Lifecycle

    /// Idempotent. Completes the errors subject.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        errorsSubject.send(completion: .finished)
    }
}
