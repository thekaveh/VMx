//
// AsyncRelayCommandBuilder — immutable fluent builder for `AsyncRelayCommand`.
//
// See spec/04-commands.md §10/§6, spec/10-builders.md, ADR-0056.
// Every setter returns a NEW builder (BLD-001 immutability contract).
// `.triggers(_:)` is additive: multiple calls accumulate (spec §6).
//
import Foundation
import Combine

public struct AsyncRelayCommandBuilder {
    private let taskClosure: (() async throws -> Void)?
    private let predicateClosure: (() -> Bool)?
    private let triggers: [AnyPublisher<Void, Never>]
    private let throwOnCancelOption: Bool

    /// Public memberwise init (zero-argument entry-point used by
    /// `AsyncRelayCommand.builder()`).
    public init() {
        self.taskClosure = nil
        self.predicateClosure = nil
        self.triggers = []
        self.throwOnCancelOption = false
    }

    private init(
        task: (() async throws -> Void)?,
        predicate: (() -> Bool)?,
        triggers: [AnyPublisher<Void, Never>],
        throwOnCancel: Bool
    ) {
        self.taskClosure = task
        self.predicateClosure = predicate
        self.triggers = triggers
        self.throwOnCancelOption = throwOnCancel
    }

    /// Sets the async task body. The closure cooperatively checks
    /// `Task.isCancelled` / `try Task.checkCancellation()`.
    public func task(_ fn: @escaping () async throws -> Void) -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder(
            task: fn,
            predicate: predicateClosure,
            triggers: triggers,
            throwOnCancel: throwOnCancelOption
        )
    }

    /// Sets the `canExecute` predicate. `nil` → always executable when idle.
    public func predicate(_ fn: @escaping () -> Bool) -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder(
            task: taskClosure,
            predicate: fn,
            triggers: triggers,
            throwOnCancel: throwOnCancelOption
        )
    }

    /// Adds a trigger. Additive: each call appends to the trigger set.
    public func triggers(_ publisher: AnyPublisher<Void, Never>) -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder(
            task: taskClosure,
            predicate: predicateClosure,
            triggers: triggers + [publisher],
            throwOnCancel: throwOnCancelOption
        )
    }

    /// Opts into throwing mode: `executeAsync()` will surface `CancellationError`
    /// to the awaiter when `cancel()` is called, instead of completing normally.
    public func throwOnCancel(_ value: Bool = true) -> AsyncRelayCommandBuilder {
        AsyncRelayCommandBuilder(
            task: taskClosure,
            predicate: predicateClosure,
            triggers: triggers,
            throwOnCancel: value
        )
    }

    /// Builds the command. Succeeds even with no task, predicate, or triggers
    /// (yielding a command whose `canExecute()` returns `true` and whose body
    /// is a no-op).
    public func build() -> AsyncRelayCommand {
        AsyncRelayCommand(
            body: taskClosure,
            predicate: predicateClosure,
            triggers: triggers,
            throwOnCancel: throwOnCancelOption
        )
    }
}
