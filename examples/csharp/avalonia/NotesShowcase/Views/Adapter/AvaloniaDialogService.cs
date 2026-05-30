using Avalonia.Controls;
using Avalonia.Platform.Storage;
using VMx.Dialogs;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// DialogService (scenario §7.1, plan §4.a): implements
/// <see cref="IDialogService"/> against Avalonia's native modal stack.
///
/// <para><b>Phase 4.a status</b>:</para>
/// <list type="bullet">
///   <item>
///     <description>
///       <see cref="PickFileToOpen"/> and <see cref="PickFileToSave"/> route to
///       <see cref="IStorageProvider"/> on the host window (Avalonia 11 surface;
///       Avalonia 10's <c>OpenFileDialog</c>/<c>SaveFileDialog</c> were retired).
///     </description>
///   </item>
///   <item>
///     <description>
///       <see cref="Confirm"/> and <see cref="Notify"/> currently throw
///       <see cref="NotImplementedException"/> — they need
///       <c>Views/Modals/ConfirmDialog.axaml</c> + <c>SaveFileDialog.axaml</c>
///       windows + a notification overlay control, which land in Phase 5.a
///       (per plan §5.a). The interface is satisfied so composition root /
///       Phase 4.b/4.c parity wiring compiles today; the missing modal calls
///       are caught by Phase 5.a tests.
///     </description>
///   </item>
/// </list>
/// </summary>
public sealed class AvaloniaDialogService : IDialogService
{
    private readonly Window _host;

    /// <summary>
    /// Creates a dialog service rooted at <paramref name="host"/>; every modal
    /// is parented to this window for correct focus management.
    /// </summary>
    /// <param name="host">The host window. Required.</param>
    /// <exception cref="ArgumentNullException">If <paramref name="host"/> is null.</exception>
    public AvaloniaDialogService(Window host)
    {
        ArgumentNullException.ThrowIfNull(host);
        _host = host;
    }

    /// <inheritdoc/>
    public async Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
    {
        var options = new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            FileTypeFilter = ToFileTypes(filter),
        };
        var files = await _host.StorageProvider.OpenFilePickerAsync(options).ConfigureAwait(true);
        var file = files.Count == 0 ? null : files[0];
        return file?.Path.LocalPath;
    }

    /// <inheritdoc/>
    public async Task<string?> PickFileToSave(
        FileFilter? filter = null,
        string? title = null,
        string? suggestedName = null)
    {
        var options = new FilePickerSaveOptions
        {
            Title = title,
            SuggestedFileName = suggestedName,
            FileTypeChoices = ToFileTypes(filter),
        };
        var file = await _host.StorageProvider.SaveFilePickerAsync(options).ConfigureAwait(true);
        return file?.Path.LocalPath;
    }

    /// <summary>
    /// Confirmation prompt. <b>Not implemented in Phase 4.a</b>: requires the
    /// <c>ConfirmDialog</c> window that Phase 5.a delivers.
    /// </summary>
    public Task<bool> Confirm(string message, string? title = null)
        => throw new NotImplementedException(
            "AvaloniaDialogService.Confirm requires the ConfirmDialog window " +
            "(plan §5.a). Phase 5.a replaces this placeholder.");

    /// <summary>
    /// Severity-tagged notification. <b>Not implemented in Phase 4.a</b>:
    /// requires the in-window notification overlay Phase 5.a delivers.
    /// </summary>
    public Task Notify(
        string message,
        string? title = null,
        NotificationSeverity severity = NotificationSeverity.Info)
        => throw new NotImplementedException(
            "AvaloniaDialogService.Notify requires the notification overlay " +
            "(plan §5.a). Phase 5.a replaces this placeholder.");

    private static IReadOnlyList<FilePickerFileType>? ToFileTypes(FileFilter? filter)
    {
        if (filter is null) return null;
        return new[]
        {
            new FilePickerFileType(filter.Description)
            {
                Patterns = filter.Extensions.ToArray(),
            },
        };
    }
}
