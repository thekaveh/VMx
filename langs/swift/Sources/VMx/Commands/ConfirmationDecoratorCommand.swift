//
// ConfirmationDecoratorCommand — gates execution on an async confirm delegate.
//
// See spec/04-commands.md §8.3 / §8.3.1 / §8.3.2, ADR-0049, and ADR-0145.
//
// Behaviour:
// - canExecute() delegates verbatim to inner.canExecute() (CMDD-008).
// - execute() is fire-and-forget: launches a Swift Task that awaits the confirm
//   gate and, only when it returns true, starts the inner command through the
//   inner's own fire-and-forget execute() (CMDD-007). An asynchronous inner
//   (an `AsyncCommand` or a nested decorator) reports its own failures on its
//   own `errors` channel; the decorator does not watch or re-emit them
//   (spec §8.3.2, CMDD-015). A throwing confirm closure is routed to this
//   decorator's `errors` channel instead of being swallowed (CMDD-010).
// - executeAsync() is the awaitable path: gates on canExecute → awaits confirm
//   → invokes the inner exactly once when true. An asynchronous inner is
//   awaited through its executeAsync(), so the awaiter completes when the inner
//   operation completes; a synchronous inner runs through execute(). Failures
//   are rethrown to the awaiter and never emitted on `errors` (CMDD-014).
// - The decorator adds no admission or cancellation of its own beyond the
//   confirm gate and disposal: the inner keeps its own busy/predicate gate and
//   cancellation outcome, and is never owned, cancelled, or disposed here
//   (CMDD-016, CMDD-017).
// - errors: AnyPublisher<Error, Never> backed by a PassthroughSubject that is
//   completed on dispose() (Combine; mirrors rxjs Subject in TS flavour).
// - canExecuteChanged forwards the inner's emissions through the decorator's
//   own stream.
// - dispose() makes the decorator inert, releases the inner subscription,
//   notifies canExecuteChanged once and completes it, and completes the errors
//   subject; idempotent. A confirmation resolving after dispose runs nothing and
//   emits nothing (spec §8.4, ADR-0134).
//
// Note: Command.execute() is non-throwing in the Swift protocol surface, so a
// synchronous inner has no failure to surface and a "throwing inner" in the TS
// sense maps here to the confirm closure throwing. The confirm parameter is
// therefore typed `() async throws -> Bool` so that CMDD-010's throwing-confirm
// scenario is directly testable.
//
import Foundation
import Combine

public final class ConfirmationDecoratorCommand: Command {
    private let inner: Command
    private let confirm: () async throws -> Bool
    private let errorsSubject = PassthroughSubject<Error, Never>()
    private let disposalLock = NSLock()
    private var disposed = false
    private let changes: WrapperChangeStream

    /// Re-reads disposal after a call-out that may have disposed this wrapper.
    private var isDisposed: Bool {
        disposalLock.lock()
        defer { disposalLock.unlock() }
        return disposed
    }

    public init(_ inner: Command, confirm: @escaping () async throws -> Bool) {
        self.inner = inner
        self.changes = WrapperChangeStream(forwarding: [inner.canExecuteChanged])
        self.confirm = confirm
    }

    // MARK: - Command

    public func canExecute() -> Bool {
        // Re-check after the call-out: the inner predicate may dispose this
        // wrapper (spec/04 §8.4).
        !isDisposed && inner.canExecute() && !isDisposed
    }

    /// Fire-and-forget. Awaits the confirm gate on a Swift Task and, when it
    /// returns true, starts the inner command through the inner's own
    /// `execute()` (spec §8.3.2).
    ///
    /// Errors thrown by the confirm gate are routed to `errors` rather than
    /// propagated to the synchronous caller (CMDD-010). An asynchronous inner
    /// reports its own failures on its own `errors` channel; this decorator
    /// neither awaits the inner operation nor re-emits its failures (CMDD-015).
    public func execute() {
        let command = UncheckedSendableBox(self)
        Task { [command] in
            await command.value.confirmThenStartInner()
        }
    }

    /// Awaitable path — gates on canExecute, awaits confirm, and invokes the
    /// inner command exactly once when confirm returns true (spec §8.3.2).
    ///
    /// An asynchronous inner — an `AsyncCommand` or another
    /// `ConfirmationDecoratorCommand` — is awaited through its own
    /// `executeAsync()`, so this call completes when the inner operation
    /// completes, not when it starts, and nested wrappers are awaited end to
    /// end. A synchronous inner runs through `execute()`. The inner's
    /// `execute()` and `executeAsync()` are never both called for one admitted
    /// call.
    ///
    /// Confirm and inner failures are rethrown to the awaiter unchanged and are
    /// not emitted on `errors`. The inner applies its own admission (a busy
    /// `AsyncRelayCommand` drops the call) and cancellation rules; this
    /// decorator adds none and never cancels or disposes the inner.
    public func executeAsync() async throws {
        // The inner predicate may dispose the decorator.
        guard canExecute(), !isDisposed else { return }
        let ok = try await confirm()
        // A confirmation that resolves after disposal runs nothing (spec §8.4).
        guard ok, !isDisposed else { return }
        switch inner {
        case let asyncInner as AsyncCommand:
            try await asyncInner.executeAsync()
        case let nested as ConfirmationDecoratorCommand:
            try await nested.executeAsync()
        default:
            inner.execute()
        }
    }

    /// Forwards the inner command's emissions until disposal, which notifies
    /// once and completes this stream (spec §8.4). The inner stream stays open.
    public var canExecuteChanged: AnyPublisher<Void, Never> {
        changes.publisher
    }

    // MARK: - Errors channel

    /// Observable that surfaces failures of the fire-and-forget `execute()`
    /// path that have no other channel: a throwing confirm delegate (CMDD-010).
    /// An asynchronous inner's failure arrives on the inner's own `errors`, not
    /// here (CMDD-015). Awaited `executeAsync()` failures are rethrown instead.
    /// Completes on `dispose()`.
    public var errors: AnyPublisher<Error, Never> {
        errorsSubject.eraseToAnyPublisher()
    }

    // MARK: - Lifecycle

    /// Makes the decorator inert, completes `canExecuteChanged` after one final
    /// notification, and completes the errors subject (spec §8.4,
    /// ADR-0134). Idempotent. The inner command stays owned by its creator: it
    /// is neither cancelled nor disposed, and an inner operation already
    /// running keeps running to completion.
    public func dispose() {
        disposalLock.lock()
        let first = !disposed
        disposed = true
        disposalLock.unlock()
        guard first else { return }
        changes.close()
        errorsSubject.send(completion: .finished)
    }

    // MARK: - Private

    /// The fire-and-forget flow behind `execute()`: awaits the confirm gate,
    /// routes its failure to `errors`, and starts the inner through its own
    /// fire-and-forget `execute()` when confirmed (spec §8.3.1 / §8.3.2).
    private func confirmThenStartInner() async {
        // The inner predicate may dispose the decorator.
        guard canExecute(), !isDisposed else { return }
        let ok: Bool
        do {
            ok = try await confirm()
        } catch {
            publishError(error)
            return
        }
        // A confirmation that resolves after disposal runs nothing (spec §8.4).
        guard ok, !isDisposed else { return }
        inner.execute()
    }

    /// `errors` completed at disposal, so a failure that arrives later is dropped.
    private func publishError(_ error: Error) {
        guard !isDisposed else { return }
        errorsSubject.send(error)
    }
}
