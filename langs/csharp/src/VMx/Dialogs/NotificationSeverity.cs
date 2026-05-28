namespace VMx.Dialogs;

/// <summary>
/// Severity level for a notification presented via <see cref="IDialogService.Notify"/>.
/// See spec/19-dialogs.md §2.
/// </summary>
public enum NotificationSeverity
{
    /// <summary>Informational message.</summary>
    Info,

    /// <summary>Warning message.</summary>
    Warning,

    /// <summary>Error message.</summary>
    Error,
}
