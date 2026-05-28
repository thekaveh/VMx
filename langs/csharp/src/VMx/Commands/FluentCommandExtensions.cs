using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Ergonomic fluent extension methods over <see cref="ICommand"/>.
/// These are pure syntactic shortcuts over the explicit decorator constructors —
/// they add no new behaviour. See spec/04-commands.md §10 and ADR-0027.
/// </summary>
public static class FluentCommandExtensions
{
    /// <summary>
    /// Returns a <see cref="ConfirmationDecoratorCommand"/> that gates execution
    /// of <paramref name="command"/> on the supplied async <paramref name="confirm"/>
    /// delegate. Equivalent to <c>new ConfirmationDecoratorCommand(command, confirm)</c>.
    /// </summary>
    public static ICommand Confirm(this ICommand command, Func<Task<bool>> confirm)
        => new ConfirmationDecoratorCommand(command, confirm);

    /// <summary>
    /// Returns a <see cref="CompositeCommand"/> where <paramref name="other"/> executes
    /// <em>before</em> <paramref name="command"/>.
    /// Equivalent to <c>new CompositeCommand(other, command)</c>.
    /// </summary>
    public static ICommand PrecedeWith(this ICommand command, ICommand other)
        => new CompositeCommand(other, command);

    /// <summary>
    /// Returns a <see cref="CompositeCommand"/> where <paramref name="other"/> executes
    /// <em>after</em> <paramref name="command"/>.
    /// Equivalent to <c>new CompositeCommand(command, other)</c>.
    /// </summary>
    public static ICommand SucceedWith(this ICommand command, ICommand other)
        => new CompositeCommand(command, other);

    /// <summary>
    /// Returns a <see cref="DecoratorCommand"/> wrapping <paramref name="command"/> with
    /// an optional extra can-execute <paramref name="predicate"/> and optional
    /// <paramref name="pre"/>/<paramref name="post"/> hooks.
    /// Passing all nulls yields a semantically transparent decorator.
    /// Equivalent to <c>new DecoratorCommand(command, pre, post, predicate)</c>.
    /// </summary>
    public static ICommand WrapWith(
        this ICommand command,
        Func<bool>? predicate = null,
        Action? pre = null,
        Action? post = null)
        => new DecoratorCommand(command, preExecute: pre, postExecute: post, extraPredicate: predicate);
}
