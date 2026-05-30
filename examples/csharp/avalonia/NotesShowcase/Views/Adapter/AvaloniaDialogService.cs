using Avalonia.Controls;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using NotesShowcase.Views.Modals;
using VMx.Dialogs;
using VMx.Notifications;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// DialogService (scenario §7.1, plan §4.a / §5.a): implements
/// <see cref="IDialogService"/> against Avalonia's native modal stack.
///
/// <para><b>Phase 5.a completion</b>:</para>
/// <list type="bullet">
///   <item>
///     <description>
///       <see cref="PickFileToOpen"/> / <see cref="PickFileToSave"/> route to
///       <see cref="IStorageProvider"/> on the host window (Avalonia 11 surface;
///       Avalonia 10's <c>OpenFileDialog</c>/<c>SaveFileDialog</c> were retired).
///     </description>
///   </item>
///   <item>
///     <description>
///       <see cref="Confirm"/> opens <see cref="ConfirmDialog"/> as a modal
///       child of the host window and resolves <c>true</c>/<c>false</c> from
///       the Yes/No buttons. Per spec §6.1, the dialog's XAML code-behind only
///       loads the XAML; this adapter (composition layer) wires the buttons.
///     </description>
///   </item>
///   <item>
///     <description>
///       <see cref="Notify"/> forwards to the optional
///       <see cref="INotificationHub"/> (the same hub that drives the in-window
///       toast overlay via <c>NotificationsVM</c>). When the hub is absent
///       (constructor without one), the call is a no-op — callers that need
///       guaranteed visibility should use <see cref="Confirm"/> or wire the
///       hub explicitly.
///     </description>
///   </item>
/// </list>
/// </summary>
public sealed class AvaloniaDialogService : IDialogService
{
    private readonly Window _host;
    private readonly INotificationHub? _notificationHub;

    /// <summary>
    /// Creates a dialog service rooted at <paramref name="host"/>; every modal
    /// is parented to this window for correct focus management.
    /// </summary>
    /// <param name="host">The host window. Required.</param>
    /// <param name="notificationHub">
    /// Optional notification hub for <see cref="Notify"/>. Default (null) makes
    /// notifications a no-op — useful for tests / headless smoke runs.
    /// </param>
    /// <exception cref="ArgumentNullException">If <paramref name="host"/> is null.</exception>
    public AvaloniaDialogService(Window host, INotificationHub? notificationHub = null)
    {
        ArgumentNullException.ThrowIfNull(host);
        _host = host;
        _notificationHub = notificationHub;
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

    /// <inheritdoc/>
    public Task<bool> Confirm(string message, string? title = null)
    {
        // Marshal to the UI thread — Confirm can be invoked from a command
        // callback running on a background scheduler. InvokeAsync over an
        // async lambda returns the unwrapped Task<bool> directly.
        return Dispatcher.UIThread.InvokeAsync(() => ShowConfirmAsync(message, title));
    }

    private async Task<bool> ShowConfirmAsync(string message, string? title)
    {
        var dialog = new ConfirmDialog
        {
            Title = title ?? "Confirm",
        };
        var messageText = dialog.FindControl<TextBlock>("MessageText");
        if (messageText is not null) messageText.Text = message;

        var tcs = new TaskCompletionSource<bool>();

        var yes = dialog.FindControl<Button>("YesButton");
        var no = dialog.FindControl<Button>("NoButton");
        if (yes is not null) yes.Click += (_, _) => { tcs.TrySetResult(true); dialog.Close(); };
        if (no is not null) no.Click += (_, _) => { tcs.TrySetResult(false); dialog.Close(); };
        dialog.Closed += (_, _) => tcs.TrySetResult(false);

        await dialog.ShowDialog(_host).ConfigureAwait(true);
        return await tcs.Task.ConfigureAwait(true);
    }

    /// <inheritdoc/>
    public Task Notify(
        string message,
        string? title = null,
        NotificationSeverity severity = NotificationSeverity.Info)
    {
        if (_notificationHub is null) return Task.CompletedTask;
        // INotificationHub's enum has no "Warning" — bucket warnings with the
        // generic Notification severity to match the host-side palette.
        var type = severity switch
        {
            NotificationSeverity.Error => NotificationType.Error,
            _ => NotificationType.Notification,
        };
        return _notificationHub.Post(new Notification(type, message));
    }

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
