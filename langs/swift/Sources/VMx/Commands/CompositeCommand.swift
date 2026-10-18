//
// CompositeCommand — aggregates N inner commands.
//
// See spec/04-commands.md §8.1 and ADR-0012.
//
// Behaviour:
// - canExecute() returns true iff at least one inner canExecute() is true (OR).
// - execute() invokes only the inners whose canExecute() is currently true.
// - canExecuteChanged forwards every inner canExecuteChanged emission through
//   the composite's own stream. With no inners it never emits until disposal.
// - dispose() makes the composite inert and is idempotent (spec §8.4,
//   ADR-0134): it releases the inner subscriptions, notifies once, and
//   completes canExecuteChanged. The inner commands stay owned by their creator.
//
import Foundation
import Combine

public final class CompositeCommand: Command {
    private let inners: [Command]
    private let disposalLock = NSLock()
    private var disposed = false
    private let changes: WrapperChangeStream

    /// Re-reads disposal after a call-out that may have disposed this wrapper.
    private var isDisposed: Bool {
        disposalLock.lock()
        defer { disposalLock.unlock() }
        return disposed
    }

    public init(_ inner: Command...) {
        self.inners = inner
        self.changes = WrapperChangeStream(forwarding: inner.map { $0.canExecuteChanged })
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
        changes.publisher
    }

    /// Makes the composite inert (spec §8.4, ADR-0134). Idempotent. Releases
    /// the inner subscriptions, notifies once, and completes
    /// `canExecuteChanged`; the inner commands stay owned by their creator.
    public func dispose() {
        disposalLock.lock()
        disposed = true
        disposalLock.unlock()
        changes.close()
    }
}
