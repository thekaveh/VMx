//
// RelayCommandOfBuilder<T> — immutable fluent builder for `RelayCommandOf<T>`.
//
// See spec/10-builders.md. Every setter copies the receiver into a new
// builder; the original is untouched (BLD-001).
//
import Foundation
import Combine

public struct RelayCommandOfBuilder<T> {
    private let taskClosure: ((T) -> Void)?
    private let predicateClosure: ((T) -> Bool)?
    private let triggers: [AnyPublisher<Void, Never>]

    public init() {
        self.taskClosure = nil
        self.predicateClosure = nil
        self.triggers = []
    }

    private init(
        task: ((T) -> Void)?,
        predicate: ((T) -> Bool)?,
        triggers: [AnyPublisher<Void, Never>]
    ) {
        self.taskClosure = task
        self.predicateClosure = predicate
        self.triggers = triggers
    }

    public func task(_ fn: @escaping (T) -> Void) -> RelayCommandOfBuilder<T> {
        RelayCommandOfBuilder(task: fn, predicate: predicateClosure, triggers: triggers)
    }

    public func predicate(_ fn: @escaping (T) -> Bool) -> RelayCommandOfBuilder<T> {
        RelayCommandOfBuilder(task: taskClosure, predicate: fn, triggers: triggers)
    }

    /// Additive: every call appends a new trigger to the set. Mirrors
    /// the TS / Python behavior.
    public func triggers(_ publisher: AnyPublisher<Void, Never>) -> RelayCommandOfBuilder<T> {
        RelayCommandOfBuilder(
            task: taskClosure,
            predicate: predicateClosure,
            triggers: triggers + [publisher]
        )
    }

    public func build() -> RelayCommandOf<T> {
        RelayCommandOf(task: taskClosure, predicate: predicateClosure, triggers: triggers)
    }
}
