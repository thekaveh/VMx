//
// FluentCommands — free-function composition helpers for Command.
//
// See spec/04-commands.md §9 and ADR-0027.
//
// These functions are thin aliases over the explicit decorator/composite
// constructors and add no new behaviour (CMD-008..CMD-011).
//
import Foundation

// MARK: - CMD-008

/// Returns a `ConfirmationDecoratorCommand` that gates execution of `command`
/// on the supplied async `confirmDelegate`.
///
/// Equivalent to `ConfirmationDecoratorCommand(command, confirm: confirmDelegate)`.
///
/// CMD-008 — `confirm(_:_:)` is equivalent to explicit `ConfirmationDecoratorCommand`
public func confirm(
    _ command: Command,
    _ confirmDelegate: @escaping () async throws -> Bool
) -> ConfirmationDecoratorCommand {
    return ConfirmationDecoratorCommand(command, confirm: confirmDelegate)
}

// MARK: - CMD-009

/// Returns a `CompositeCommand` where `other` executes *before* `command`.
///
/// Equivalent to `CompositeCommand(other, command)`.
///
/// CMD-009 — `precedeWith(_:_:)` is equivalent to `CompositeCommand(other, command)`
public func precedeWith(_ command: Command, _ other: Command) -> CompositeCommand {
    return CompositeCommand(other, command)
}

// MARK: - CMD-010

/// Returns a `CompositeCommand` where `other` executes *after* `command`.
///
/// Equivalent to `CompositeCommand(command, other)`.
///
/// CMD-010 — `succeedWith(_:_:)` is equivalent to `CompositeCommand(command, other)`
public func succeedWith(_ command: Command, _ other: Command) -> CompositeCommand {
    return CompositeCommand(command, other)
}

// MARK: - CMD-011

/// Returns a `DecoratorCommand` wrapping `command` with optional extra
/// `predicate`, `pre`, and `post` hooks.
///
/// Equivalent to `DecoratorCommand(command, preExecute: pre, postExecute: post, extraPredicate: predicate)`.
///
/// Passing all `nil` / omitting all arguments yields a semantically transparent decorator.
///
/// CMD-011 — `wrapWith(_:predicate:pre:post:)` is equivalent to explicit `DecoratorCommand`
public func wrapWith(
    _ command: Command,
    predicate: (() -> Bool)? = nil,
    pre: (() -> Void)? = nil,
    post: (() -> Void)? = nil
) -> DecoratorCommand {
    return DecoratorCommand(
        command,
        preExecute: pre,
        postExecute: post,
        extraPredicate: predicate
    )
}
