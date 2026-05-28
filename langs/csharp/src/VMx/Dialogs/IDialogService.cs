namespace VMx.Dialogs;

/// <summary>
/// Host-side service contract for modal interactions: file pick, confirm prompt,
/// and severity-tagged notify. See spec/19-dialogs.md and ADR-0029.
/// </summary>
public interface IDialogService
{
    /// <summary>
    /// Presents a file-open dialog. Returns the selected path, or <c>null</c> on cancel.
    /// </summary>
    Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null);

    /// <summary>
    /// Presents a file-save dialog. Returns the selected path, or <c>null</c> on cancel.
    /// </summary>
    Task<string?> PickFileToSave(
        FileFilter? filter = null,
        string? title = null,
        string? suggestedName = null);

    /// <summary>
    /// Presents a confirmation prompt. Returns <c>true</c> when confirmed,
    /// <c>false</c> when cancelled or dismissed.
    /// </summary>
    Task<bool> Confirm(string message, string? title = null);

    /// <summary>
    /// Presents a notification with the given severity. Severity defaults to
    /// <see cref="NotificationSeverity.Info"/> when not supplied.
    /// </summary>
    Task Notify(
        string message,
        string? title = null,
        NotificationSeverity severity = NotificationSeverity.Info);
}
