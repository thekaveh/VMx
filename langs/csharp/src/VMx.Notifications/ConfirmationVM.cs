using System.Reactive.Concurrency;
using System.Windows.Input;
using VMx.Commands;

namespace VMx.Notifications;

/// <summary>
/// Render-side ViewModel for a confirmation <see cref="Notification"/>.
/// Extends <see cref="NotificationVM"/> with explicit <see cref="ApproveCommand"/>
/// and <see cref="RejectCommand"/>. Default lifespan is 300 seconds.
///
/// Unlike <see cref="NotificationVM"/>, ConfirmationVM does NOT auto-resolve on
/// lifespan expiry — timeout means "user did not decide".
///
/// See spec/16-notifications.md §ConfirmationVM and ADR-0031.
/// </summary>
public sealed class ConfirmationVM : NotificationVM
{
    /// <summary>
    /// Creates a <see cref="ConfirmationVM"/>.
    /// </summary>
    /// <param name="notification">The confirmation notification to render.</param>
    /// <param name="hub">Hub used to resolve the notification.</param>
    /// <param name="scheduler">Scheduler for time advancement.</param>
    /// <param name="lifespan">Override the default 300-second lifespan.</param>
    public ConfirmationVM(
        Notification notification,
        INotificationHub hub,
        IScheduler scheduler,
        TimeSpan? lifespan = null)
        : base(notification, hub, scheduler, lifespan ?? TimeSpan.FromSeconds(300))
    {
        ApproveCommand = RelayCommand.Builder()
            .Task(() => ResolveWith(NotificationReaction.Approve))
            .Build();

        RejectCommand = RelayCommand.Builder()
            .Task(() => ResolveWith(NotificationReaction.Reject))
            .Build();
    }

    /// <summary>Resolves the notification with <see cref="NotificationReaction.Approve"/>.</summary>
    public ICommand ApproveCommand { get; }

    /// <summary>Resolves the notification with <see cref="NotificationReaction.Reject"/>.</summary>
    public ICommand RejectCommand { get; }

    /// <summary>
    /// ConfirmationVM does NOT auto-resolve on lifespan expiry.
    /// Timeout means "user did not decide"; the notification remains pending.
    /// </summary>
    protected override void OnExpire()
    {
        // Intentional no-op. ConfirmationVM requires an explicit user action.
    }

    /// <inheritdoc/>
    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            if (ApproveCommand is IDisposable a) a.Dispose();
            if (RejectCommand is IDisposable r) r.Dispose();
        }

        base.Dispose(disposing);
    }
}
