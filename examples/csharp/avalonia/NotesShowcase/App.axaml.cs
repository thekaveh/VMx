using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views;
using NotesShowcase.Views.Adapter;
using VMx.Notifications;
using VMx.Services;

namespace NotesShowcase;

/// <summary>
/// Avalonia application bootstrap and composition root.
///
/// <para>
/// Per spec §6.1, view <c>.axaml.cs</c> files are restricted to a single
/// <see cref="AvaloniaXamlLoader.Load(object)"/> call. <see cref="App"/> is the
/// documented exception: this is the composition layer, not a view. It wires
/// the repository, hubs, dispatcher, dialog service, and root
/// <see cref="WorkspaceVM"/>; constructs the <see cref="MainWindow"/>; and
/// disposes the workspace on shutdown.
/// </para>
/// </summary>
public class App : Application
{
    private WorkspaceVM? _workspace;

    /// <inheritdoc/>
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    /// <inheritdoc/>
    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var window = BuildMainWindow();
            desktop.MainWindow = window;
            desktop.ShutdownRequested += (_, _) => _workspace?.Dispose();
        }
        base.OnFrameworkInitializationCompleted();
    }

    /// <summary>
    /// Composition root. Wires the in-memory repo, hubs, dispatcher, dialog
    /// service, and root <see cref="WorkspaceVM"/>; fires async construct;
    /// returns the data-context'd <see cref="MainWindow"/>. <c>protected</c> so
    /// the headless smoke test's <c>HeadlessTestApp</c> can skip it.
    /// </summary>
    protected virtual MainWindow BuildMainWindow()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var hub = new MessageHub();
        var notifications = new NotificationHub();
        var dispatcher = new AvaloniaDispatcher();
        var window = new MainWindow();
        var dialogs = new AvaloniaDialogService(window, notifications);

        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(dialogs)
            .NotificationHub(notifications)
            .MessageHub(hub)
            .Dispatcher(dispatcher)
            .Build();
        _workspace = workspace;

        // Fire-and-forget — the UI binds to live properties as Construct
        // populates them; the ~300/150 ms repo delays don't block startup.
        _ = workspace.ConstructAsync();

        // VMX-129: drive the application theme from the workspace-owned ThemeVM
        // (THEME-001..005). The adapter applies the current model immediately
        // and re-applies on every effective change.
        ThemeAdapter.Apply(workspace.Theme, this);

        window.DataContext = workspace;
        return window;
    }
}
