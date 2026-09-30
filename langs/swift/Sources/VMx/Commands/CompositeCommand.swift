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
// - dispose() makes the composite inert and is idempotent (spec §8.4,
//   ADR-0134); the inner commands stay owned by their creator.
//
import Foundation
import Combine

public final class CompositeCommand: Command {
    private let inners: [Command]
    private let disposalLock = NSLock()
    private var disposed = false

    /// Re-reads disposal after a call-out that may have disposed this wrapper.
    private var isDisposed: Bool {
        disposalLock.lock()
        defer { disposalLock.unlock() }
        return disposed
    }

    public init(_ inner: Command...) {
        self.inners = inner
    }

    public func canExecute() -> Bool {
        guard !isDisposed else { return false }
        for c in inners where c.canExecute() { return !isDisposed }
        return false
    }

    public func execute() {
        // A child may dispose the composite; no later child runs once disposal
        // is observed (spec §8.4, ADR-0134).
        for c in inners {
            if isDisposed { return }
            if c.canExecute() && !isDisposed { c.execute() }
        }
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        if inners.isEmpty {
            return Empty<Void, Never>(completeImmediately: false).eraseToAnyPublisher()
        }
        return Publishers.MergeMany(inners.map { $0.canExecuteChanged })
            .eraseToAnyPublisher()
    }

    /// Makes the composite inert (spec §8.4, ADR-0134). Idempotent. The inner
    /// commands stay owned by their creator, and `canExecuteChanged` is a lazy
    /// merge of their publishers, so nothing else is released here.
    public func dispose() {
        disposalLock.lock()
        disposed = true
        disposalLock.unlock()
    }
}
