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
// - canExecuteChanged delegates to the inner command's publisher.
// - dispose() is a no-op: DecoratorCommand does not own the inner command.
//
import Foundation
import Combine

public final class DecoratorCommand: Command {
    private let inner: Command
    private let preExecute: (() -> Void)?
    private let postExecute: (() -> Void)?
    private let extraPredicate: (() -> Bool)?

    public init(
        _ inner: Command,
        preExecute: (() -> Void)? = nil,
        postExecute: (() -> Void)? = nil,
        extraPredicate: (() -> Bool)? = nil
    ) {
        self.inner = inner
        self.preExecute = preExecute
        self.postExecute = postExecute
        self.extraPredicate = extraPredicate
    }

    public func canExecute() -> Bool {
        guard inner.canExecute() else { return false }
        return extraPredicate?() ?? true
    }

    public func execute() {
        guard canExecute() else { return }
        preExecute?()
        defer { postExecute?() }
        inner.execute()
    }

    public var canExecuteChanged: AnyPublisher<Void, Never> {
        inner.canExecuteChanged
    }

    /// No-op: DecoratorCommand does not own the inner command and holds no
    /// subscriptions of its own. Provided for teardown symmetry with C#.
    public func dispose() {}
}
