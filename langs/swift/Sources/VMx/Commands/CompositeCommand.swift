//
// CompositeCommand — aggregates N inner commands.
//
// See spec/04-commands.md §8.1 and ADR-0012.
//
// Behaviour:
// - canExecute() returns true iff at least one inner canExecute() is true (OR).
// - execute() invokes only the inners whose canExecute() is currently true.
// - canExecuteChanged merges all inner canExecuteChanged publishers.
//   When there are no inners, it is a never-completing empty publisher
//   (Combine analogue of RxJS NEVER).
// - dispose() is idempotent; provided for teardown symmetry with C#.
//
import Foundation
import Combine

public final class CompositeCommand: Command {
    private let inners: [Command]

    public init(_ inner: Command...) {
        self.inners = inner
    }

    public func canExecute() -> Bool {
        for c in inners where c.canExecute() { return true }
        return false
    }

    public func execute() {
        for c in inners where c.canExecute() { c.execute() }
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        if inners.isEmpty {
            return Empty<Void, Never>(completeImmediately: false).eraseToAnyPublisher()
        }
        return Publishers.MergeMany(inners.map { $0.canExecuteChanged })
            .eraseToAnyPublisher()
    }

    /// No-op: a `CompositeCommand` does not own its inner commands (they are
    /// supplied by the caller, who owns their lifetime) and holds no
    /// subscriptions of its own. Provided for teardown symmetry with C#.
    public func dispose() {}
}
