namespace VMx.Dialogs;

/// <summary>
/// Null-object implementation of <see cref="IDialogService"/> per ADR-0017.
/// All methods return the safest default: file pickers return <c>null</c>,
/// <see cref="Confirm"/> returns <c>false</c>, <see cref="Notify"/> is a no-op.
/// Stateless and safe to share. See spec/19-dialogs.md §3.
/// </summary>
public sealed class NullDialogService : IDialogService
{
    /// <summary>Shared singleton instance (the service holds no state).</summary>
    public static NullDialogService Instance { get; } = new();

    private NullDialogService() { }

    /// <inheritdoc/>
    public Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
        => Task.FromResult<string?>(null);

    /// <inheritdoc/>
    public Task<string?> PickFileToSave(
        FileFilter? filter = null,
        string? title = null,
        string? suggestedName = null)
        => Task.FromResult<string?>(null);

    /// <inheritdoc/>
    public Task<bool> Confirm(string message, string? title = null)
        => Task.FromResult(false);

    /// <inheritdoc/>
    public Task Notify(
        string message,
        string? title = null,
        NotificationSeverity severity = NotificationSeverity.Info)
        => Task.CompletedTask;
}
