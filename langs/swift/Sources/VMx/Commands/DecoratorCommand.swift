//
// DecoratorCommand — wraps a single inner command with pre/post + extra-predicate.
//
// See spec/04-commands.md §8.2 and ADR-0012.
//
// Behaviour:
// - canExecute() = inner.canExecute() && (extraPredicate?() ?? true)
// - execute() when canExecute() is true: runs preExecute → inner.execute()
//   → postExecute, with postExecute in a `defer` block so it runs even if
//   inner.execute() were ever to throw (provides "busy-flag" teardown parity
//   with the TS/C# flavours whose inner can throw).
// - execute() is a complete no-op (pre/inner/post all skipped) when
//   canExecute() is false.
// - canExecuteChanged forwards the inner command's emissions through the
//   decorator's own stream.
// - dispose() makes the decorator inert and is idempotent (spec §8.4,
//   ADR-0134): it releases the inner subscription, notifies once, and
//   completes canExecuteChanged. The inner command stays owned by its creator.
//
import Foundation
import Combine

public final class DecoratorCommand: Command {
    private let inner: Command
    private let preExecute: (() -> Void)?
    private let postExecute: (() -> Void)?
    private let extraPredicate: (() -> Bool)?
    private let disposalLock = NSLock()
    private var disposed = false
    private let changes: WrapperChangeStream

    /// Re-reads disposal after a call-out that may have disposed this wrapper.
    private var isDisposed: Bool {
        disposalLock.lock()
        defer { disposalLock.unlock() }
        return disposed
    }

    public init(
        _ inner: Command,
        preExecute: (() -> Void)? = nil,
        postExecute: (() -> Void)? = nil,
        extraPredicate: (() -> Bool)? = nil
    ) {
        self.inner = inner
        self.changes = WrapperChangeStream(forwarding: [inner.canExecuteChanged])
        self.preExecute = preExecute
        self.postExecute = postExecute
        self.extraPredicate = extraPredicate
    }

    public func canExecute() -> Bool {
        guard !isDisposed, inner.canExecute() else { return false }
        // The extra predicate may dispose the decorator.
        let allowed = extraPredicate?() ?? true
        return allowed && !isDisposed
    }

    public func execute() {
        guard canExecute() else { return }
        preExecute?()
        defer { postExecute?() }
        // The pre-action may dispose the decorator: skip the inner command but
        // keep the admitted pre/post pair balanced (spec §8.4, ADR-0134).
        guard !isDisposed else { return }
        inner.execute()
    }

    /// Forwards the inner command's emissions until disposal, which notifies
    /// once and completes this stream (spec §8.4). The inner stream stays open.
    public var canExecuteChanged: AnyPublisher<Void, Never> {
        changes.publisher
    }

    /// Makes the decorator inert (spec §8.4, ADR-0134). Idempotent. Releases
    /// the inner subscription, notifies once, and completes
    /// `canExecuteChanged`; the inner command stays owned by its creator.
    public func dispose() {
        disposalLock.lock()
        disposed = true
        disposalLock.unlock()
        changes.close()
    }
}
