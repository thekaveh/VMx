//
// RelayCommandBuilder — immutable fluent builder for `RelayCommand`.
//
// See spec/10-builders.md. Every setter copies the receiver into a new
// builder; the original is untouched (BLD-001).
//
import Foundation
import Combine

public struct RelayCommandBuilder {
    private let taskClosure: (() -> Void)?
    private let predicateClosure: (() -> Bool)?
    private let triggers: [AnyPublisher<Void, Never>]

    public init() {
        self.taskClosure = nil
        self.predicateClosure = nil
        self.triggers = []
    }

    private init(
        task: (() -> Void)?,
        predicate: (() -> Bool)?,
        triggers: [AnyPublisher<Void, Never>]
    ) {
        self.taskClosure = task
        self.predicateClosure = predicate
        self.triggers = triggers
    }

    public func task(_ fn: @escaping () -> Void) -> RelayCommandBuilder {
        RelayCommandBuilder(task: fn, predicate: predicateClosure, triggers: triggers)
    }

    public func predicate(_ fn: @escaping () -> Bool) -> RelayCommandBuilder {
        RelayCommandBuilder(task: taskClosure, predicate: fn, triggers: triggers)
    }

    /// Additive: every call appends a new trigger to the set. Mirrors
    /// the TS / Python behavior.
    public func triggers(_ publisher: AnyPublisher<Void, Never>) -> RelayCommandBuilder {
        RelayCommandBuilder(
            task: taskClosure,
            predicate: predicateClosure,
            triggers: triggers + [publisher]
        )
    }

    public func build() -> RelayCommand {
        RelayCommand(task: taskClosure, predicate: predicateClosure, triggers: triggers)
    }
}
