using System.Windows.Input;
using VMx.Dialogs;

namespace VMx.Commands;

/// <summary>
/// Ergonomic fluent extension methods over <see cref="ICommand"/>.
/// These are pure syntactic shortcuts over the explicit decorator constructors —
/// they add no new behaviour. See spec/04-commands.md §9 and ADR-0027.
///
/// <para>
/// Every decorator produced here implements <see cref="IDisposable"/> (it
/// subscribes to its inner command's <c>CanExecuteChanged</c> in its
/// constructor and detaches only on dispose). The return type is
/// <see cref="ICommand"/> for ergonomic chaining, which hides that disposability.
/// To avoid leaking the intermediate decorators in a chain, pass a
/// <c>track</c> collection (e.g. a
/// <see cref="System.Reactive.Disposables.CompositeDisposable"/>): each created
/// decorator registers itself, so disposing the collection tears down the whole
/// chain in one call (VMX-012).
/// </para>
/// </summary>
public static class FluentCommandExtensions
{
    /// <summary>
    /// Returns a <see cref="ConfirmationDecoratorCommand"/> that gates execution
    /// of <paramref name="command"/> on the supplied async <paramref name="confirm"/>
    /// delegate. Equivalent to <c>new ConfirmationDecoratorCommand(command, confirm)</c>.
    /// </summary>
    public static ICommand Confirm(
        this ICommand command,
        Func<Task<bool>> confirm,
        ICollection<IDisposable>? track = null)
        => Tracked(new ConfirmationDecoratorCommand(command, confirm), track);

    /// <summary>
    /// Returns a <see cref="ConfirmationDecoratorCommand"/> that gates execution
    /// of <paramref name="command"/> on <see cref="IDialogService.Confirm(string, string?)"/>
    /// called with <paramref name="prompt"/>.
    /// Equivalent to <c>command.Confirm(() => dialogService.Confirm(prompt))</c>.
    /// </summary>
    public static ICommand Confirm(
        this ICommand command,
        IDialogService dialogService,
        string prompt,
        ICollection<IDisposable>? track = null)
        => command.Confirm(() => dialogService.Confirm(prompt), track);

    /// <summary>
    /// Returns a <see cref="CompositeCommand"/> where <paramref name="other"/> executes
    /// <em>before</em> <paramref name="command"/>.
    /// Equivalent to <c>new CompositeCommand(other, command)</c>.
    /// </summary>
    public static ICommand PrecedeWith(
        this ICommand command,
        ICommand other,
        ICollection<IDisposable>? track = null)
        => Tracked(new CompositeCommand(other, command), track);

    /// <summary>
    /// Returns a <see cref="CompositeCommand"/> where <paramref name="other"/> executes
    /// <em>after</em> <paramref name="command"/>.
    /// Equivalent to <c>new CompositeCommand(command, other)</c>.
    /// </summary>
    public static ICommand SucceedWith(
        this ICommand command,
        ICommand other,
        ICollection<IDisposable>? track = null)
        => Tracked(new CompositeCommand(command, other), track);

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
        Action? post = null,
        ICollection<IDisposable>? track = null)
        => Tracked(
            new DecoratorCommand(command, preExecute: pre, postExecute: post, extraPredicate: predicate),
            track);

    /// <summary>
    /// Registers <paramref name="decorator"/> into <paramref name="track"/> (when
    /// supplied) so the caller can dispose every chained intermediate at once,
    /// then returns it as an <see cref="ICommand"/>.
    /// </summary>
    private static T Tracked<T>(T decorator, ICollection<IDisposable>? track)
        where T : ICommand, IDisposable
    {
        track?.Add(decorator);
        return decorator;
    }
}
