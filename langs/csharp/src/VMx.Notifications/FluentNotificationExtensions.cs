using System.Windows.Input;
using VMx.Commands;

namespace VMx.Notifications;

/// <summary>
/// Fluent extension methods that bridge <see cref="INotificationHub"/> to the
/// <c>VMx.Commands</c> fluent API. Lives in the <c>VMx.Notifications</c> assembly
/// so that the core commands module carries no hard dependency on the
/// notifications sub-package. See spec/04-commands.md §10 and ADR-0027.
/// </summary>
public static class FluentNotificationExtensions
{
    /// <summary>
    /// Returns a <see cref="ConfirmationDecoratorCommand"/> that gates execution of
    /// <paramref name="command"/> on a Confirmation notification posted to
    /// <paramref name="hub"/> with the given <paramref name="prompt"/>.
    /// Equivalent to <c>command.Confirm(ConfirmHelper.MakeConfirm(hub, prompt))</c>.
    /// </summary>
    public static ICommand Confirm(
        this ICommand command,
        INotificationHub hub,
        string prompt)
        => command.Confirm(ConfirmHelper.MakeConfirm(hub, prompt));
}
