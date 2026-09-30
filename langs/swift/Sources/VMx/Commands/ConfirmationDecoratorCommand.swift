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
// - dispose() makes the decorator inert and completes the errors subject;
//   idempotent. A confirmation resolving after dispose runs nothing and
//   emits nothing (spec §8.4, ADR-0134).
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
    private let disposalLock = NSLock()
    private var disposed = false

    /// Re-reads disposal after a call-out that may have disposed this wrapper.
    private var isDisposed: Bool {
        disposalLock.lock()
        defer { disposalLock.unlock() }
        return disposed
    }

    public init(_ inner: Command, confirm: @escaping () async throws -> Bool) {
        self.inner = inner
        self.confirm = confirm
    }

    // MARK: - Command

    public func canExecute() -> Bool {
        !isDisposed && inner.canExecute()
    }

    /// Fire-and-forget. Errors from the confirm gate are routed to `errors`
    /// rather than propagated to the synchronous caller (CMDD-010).
    public func execute() {
        let command = UncheckedSendableBox(self)
        Task { [command] in
            do {
                try await command.value.executeAsync()
            } catch {
                command.value.publishError(error)
            }
        }
    }

    /// Awaitable path — gates on canExecute, awaits confirm, runs inner when
    /// true. Rethrows inline so the caller can observe confirm errors directly.
    ///
    /// An `AsyncCommand` inner is awaited rather than fire-and-forgotten:
    /// spec/04 §8.3 defines this entry-point as sequencing the confirm →
    /// inner flow inline, and C#'s `inner.Execute` runs an async body
    /// synchronously up to its first await, so a completing inner is
    /// observable when the awaiter resumes. Swift's non-awaited `execute()`
    /// would defer the whole body to a detached Task, losing that ordering.
    public func executeAsync() async throws {
        // The inner predicate may dispose the decorator.
        guard canExecute(), !isDisposed else { return }
        let ok = try await confirm()
        // A confirmation that resolves after disposal runs nothing (spec §8.4).
        guard ok, !isDisposed else { return }
        if let asyncInner = inner as? AsyncCommand {
            try await asyncInner.executeAsync()
        } else {
            inner.execute()
        }
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

    /// Makes the decorator inert and completes the errors subject (spec §8.4,
    /// ADR-0134). Idempotent. The inner command stays owned by its creator.
    public func dispose() {
        disposalLock.lock()
        let first = !disposed
        disposed = true
        disposalLock.unlock()
        guard first else { return }
        errorsSubject.send(completion: .finished)
    }

    /// `errors` completed at disposal, so a failure that arrives later is dropped.
    private func publishError(_ error: Error) {
        guard !isDisposed else { return }
        errorsSubject.send(error)
    }
}
