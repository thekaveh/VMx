namespace VMx.Notifications;

/// <summary>
/// Helper that bridges an <see cref="INotificationHub"/> to the
/// <c>Func&lt;Task&lt;bool&gt;&gt;</c> shape used by
/// <c>ConfirmationDecoratorCommand</c>. See spec/16-notifications.md
/// §"Bridging command decorators".
/// </summary>
public static class ConfirmHelper
{
    /// <summary>
    /// Returns a confirm-delegate that posts a Confirmation notification to
    /// <paramref name="hub"/> with <paramref name="prompt"/> and returns true
    /// iff the resolution is <see cref="NotificationReaction.Approve"/>.
    /// </summary>
    public static Func<Task<bool>> MakeConfirm(INotificationHub hub, string prompt)
    {
        return async () =>
        {
            var notification = new Notification(NotificationType.Confirmation, prompt);
            var reaction = await hub.Post(notification).ConfigureAwait(false);
            return reaction == NotificationReaction.Approve;
        };
    }
}
