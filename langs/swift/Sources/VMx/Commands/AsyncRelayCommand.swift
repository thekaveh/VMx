//
// AsyncRelayCommand — cancellable async `Command` backed by a Swift Task body.
//
// See spec/04-commands.md §10, ADR-0056.
//
// Two-runtime split (per ADR-0056 §2.1):
// - The cancellable *body* uses **Swift structured concurrency** (Task).
//   The body cooperatively checks `Task.isCancelled` / `try Task.checkCancellation()`.
// - Reactive *channels* (`canExecuteChanged`, `errors`) use **Combine**
//   (PassthroughSubject), consistent with the other Combine-based VMx types.
// - TypeScript uses AbortSignal; C# uses CancellationToken; Swift uses Task
//   cancellation — the conceptual shape is identical (ADR-0006).
//
// Behaviour contract:
// - While executing, `canExecute()` returns false (prevents double-run).
// - `cancel()` cancels the in-flight Task. By default, `executeAsync()` completes
//   normally on cancel (DIA-007 non-throwing default). Opt into `CancellationError`
//   surfacing via `.throwOnCancel()` on the builder.
// - Command-initiated cancellation is the only failure swallowed by default;
//   external (parent-Task) cancellation is always re-raised.
// - Non-cancellation task faults propagate from `executeAsync()` to the awaiter;
//   on the fire-and-forget `execute()` path they route to `errors`.
// - `canExecuteChanged` fires when in-flight state flips (start and finish).
// - `dispose()` is idempotent.
//
import Foundation
import Combine

// MARK: - AsyncCommand Protocol

/// Async, cancellable variant of `Command`. Mirrors `IAsyncCommand` in the
/// C# / Python / TypeScript flavors (spec/04-commands.md §10, ADR-0056).
public protocol AsyncCommand: Command {
    /// True while an execution is in flight.
    var isExecuting: Bool { get }

    /// Awaitable entry-point. Completes when the body finishes, is cancelled,
    /// or faults (non-cancel faults propagate to the awaiter). By default,
    /// command-initiated cancellation completes normally; opt into `CancellationError`
    /// surfacing via the builder's `.throwOnCancel()`.
    func executeAsync() async throws

    /// Requests cancellation of the in-flight task. No-op when idle.
    func cancel()
}

// MARK: - AsyncRelayCommand

/// Cancellable async command. Build via `AsyncRelayCommand.builder()`.
public final class AsyncRelayCommand: AsyncCommand {

    // MARK: Private storage

    private let body: (() async throws -> Void)?
    private let predicate: (() -> Bool)?
    private let throwOnCancelFlag: Bool
    private let canExecuteChangedSubject = PassthroughSubject<Void, Never>()
    private let errorsSubject = PassthroughSubject<Error, Never>()
    private var triggerCancellables: Set<AnyCancellable> = []
    private let stateQueue = DispatchQueue(label: "VMx.AsyncRelayCommand.state")

    /// Closure that cancels the in-flight task; set on each `executeAsync()` run.
    private var cancelHandle: (() -> Void)?

    /// Set to `true` by our own `cancel()` so the catch-block can distinguish
    /// command-initiated cancellation from external (parent-Task) cancellation.
    private var cancelRequested: Bool = false

    private var disposed: Bool = false

    // MARK: Initialiser

    public init(
        body: (() async throws -> Void)?,
        predicate: (() -> Bool)?,
        triggers: [AnyPublisher<Void, Never>],
        throwOnCancel: Bool
    ) {
        self.body = body
        self.predicate = predicate
        self.throwOnCancelFlag = throwOnCancel

        let subject = canExecuteChangedSubject
        for trigger in triggers {
            trigger
                .sink { _ in subject.send(()) }
                .store(in: &triggerCancellables)
        }
    }

    // MARK: - AsyncCommand

    /// True while an execution is in flight.
    private var _isExecuting: Bool = false

    public var isExecuting: Bool {
        stateQueue.sync { _isExecuting }
    }

    /// Awaitable entry-point.
    ///
    /// Guards against double-run (`isExecuting` / predicate), flips `isExecuting`
    /// and fires `canExecuteChanged` on start and finish.  Handles `CancellationError`
    /// per the `throwOnCancelFlag` / `cancelRequested` state (spec §10.3).
    public func executeAsync() async throws {
        guard canExecute() else { return }

        let began = stateQueue.sync { () -> Bool in
            guard !disposed && !_isExecuting else { return false }
            cancelRequested = false
            _isExecuting = true
            return true
        }
        guard began else {
            return
        }
        raiseCanExecuteChanged()

        // Wrap the body in a Task so `cancel()` can cancel it independently of
        // the calling Task's lifetime.
        let bodyTask = Task { [body] in
            try await body?()
        }
        stateQueue.sync {
            cancelHandle = { bodyTask.cancel() }
        }

        defer {
            let shouldNotify = stateQueue.sync { () -> Bool in
                cancelHandle = nil
                _isExecuting = false
                return !disposed
            }
            if shouldNotify {
                raiseCanExecuteChanged()
            }
        }

        do {
            try await withTaskCancellationHandler {
                try await bodyTask.value
            } onCancel: {
                bodyTask.cancel()
            }
        } catch is CancellationError {
            // Command-initiated cancel (cancelRequested == true) is swallowed by
            // default (DIA-007 non-throwing alignment).
            // External (parent-Task) cancellation (cancelRequested == false) is
            // always re-raised so Swift's structured concurrency semantics are
            // preserved (spec §10.3).
            // throwOnCancelFlag re-raises for command-initiated cancel too.
            let requested = stateQueue.sync { cancelRequested }
            if throwOnCancelFlag || !requested {
                throw CancellationError()
            }
            // else: complete normally — no throw
        }
        // Non-CancellationError faults propagate to the awaiter via implicit rethrow.
    }

    /// Fire-and-forget entry-point (the synchronous `Command.execute()` path).
    /// Non-cancellation faults from `executeAsync()` are routed to `errors`
    /// instead of being swallowed or becoming an unobserved faulted Task.
    public func execute() {
        guard canExecute() else { return }
        Task {
            do {
                try await self.executeAsync()
            } catch is CancellationError {
                return
            } catch {
                let isDisposed = self.stateQueue.sync { self.disposed }
                guard !isDisposed else { return }
                self.errorsSubject.send(error)
            }
        }
    }

    /// Requests cancellation of the in-flight task. No-op when idle.
    public func cancel() {
        let handle = stateQueue.sync { () -> (() -> Void)? in
            cancelRequested = true
            return cancelHandle
        }
        handle?()
    }

    // MARK: - Command

    /// Returns false while in-flight (double-run guard) and delegates to the
    /// optional predicate otherwise. No predicate → true unconditionally.
    /// The stored predicate is non-throwing (`() -> Bool`), matching the
    /// cross-flavor contract that predicates must not raise (spec §2).
    public func canExecute() -> Bool {
        if stateQueue.sync(execute: { disposed || _isExecuting }) { return false }
        guard let predicate else { return true }
        return predicate()
    }

    /// Publisher that fires whenever `canExecute()` may have changed.
    public var canExecuteChanged: AnyPublisher<Void, Never> {
        canExecuteChangedSubject.eraseToAnyPublisher()
    }

    /// Emits one re-evaluation notification without invoking user closures.
    /// Valid while idle or in flight; calls after disposal are no-ops.
    public func raiseCanExecuteChanged() {
        let shouldNotify = stateQueue.sync { !disposed }
        guard shouldNotify else { return }
        canExecuteChangedSubject.send(())
    }

    // MARK: - Errors channel

    /// Surfaces non-cancellation faults from the fire-and-forget `execute()` path.
    /// Cancellations never appear here. Completes on `dispose()`.
    public var errors: AnyPublisher<Error, Never> {
        errorsSubject.eraseToAnyPublisher()
    }

    // MARK: - Lifecycle

    /// Idempotent. Cancels any in-flight task and completes Combine subjects.
    public func dispose() {
        let result = stateQueue.sync { () -> (Bool, (() -> Void)?) in
            guard !disposed else { return (false, nil) }
            disposed = true
            let handle = cancelHandle
            cancelHandle = nil
            return (true, handle)
        }
        guard result.0 else { return }
        result.1?()
        triggerCancellables.removeAll()
        canExecuteChangedSubject.send(completion: .finished)
        errorsSubject.send(completion: .finished)
    }

    // MARK: - Builder

    public static func builder() -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder()
    }
}
