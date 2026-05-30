using System.Collections;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.VisualTree;
using NotesShowcase;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views;
using NotesShowcase.Views.Adapter;
using VMx.Dialogs;
using VMx.Notifications;
using VMx.Services;
using Xunit;

// Register the test application — Avalonia.Headless.XUnit looks this up via
// the assembly attribute to know how to spin up its in-process display.
[assembly: AvaloniaTestApplication(typeof(NotesShowcase.Tests.Views.HeadlessTestApp))]

namespace NotesShowcase.Tests.Views;

/// <summary>
/// Headless smoke test (plan §5.a.headless / scenario §9.3): the app launches
/// in-process under <see cref="AvaloniaHeadlessPlatform"/>, the main window
/// renders, and the notebooks tree reflects the four root notebooks from the
/// seed (Work / Reviews / Personal / Archive).
/// </summary>
public sealed class HeadlessSmokeTests
{
    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task MainWindow_shows_and_lists_four_root_notebooks_after_construct()
    {
        // Build a synthetic workspace with zero repo latency so the test is
        // deterministic without timer pumping.
        var seed = SeedData.Build();
        var repo = new InMemoryNoteRepository(
            seed,
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            deleteNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero,
            exportDelay: TimeSpan.Zero);
        var hub = new MessageHub();
        var dispatcher = new AvaloniaDispatcher();
        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(NullDialogService.Instance)
            .NotificationHub(new NotificationHub())
            .MessageHub(hub)
            .Dispatcher(dispatcher)
            .Build();
        await workspace.ConstructAsync();

        var window = new MainWindow { DataContext = workspace };
        window.Show();
        window.UpdateLayout();

        var tree = window.FindDescendantByName("NotebooksTree") as TreeView;
        Assert.NotNull(tree);
        Assert.Equal(4, ((IEnumerable)tree!.ItemsSource!).Cast<object>().Count());

        workspace.Dispose();
        window.Close();
    }
}

/// <summary>
/// Headless test app — reuses <see cref="App"/>'s XAML (theme + styles) but
/// skips the production composition. The smoke test builds its own
/// <see cref="WorkspaceVM"/> and <see cref="MainWindow"/> with controlled
/// (zero-latency) services, so we deliberately suppress the base
/// <c>OnFrameworkInitializationCompleted</c> work.
/// </summary>
public sealed class HeadlessTestApp : App
{
    /// <inheritdoc/>
    public override void OnFrameworkInitializationCompleted()
    {
        // Intentionally do not call base — the test owns the window lifecycle.
    }

    /// <summary>Builds the AppBuilder used by Avalonia.Headless.XUnit.</summary>
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<HeadlessTestApp>()
            .UseHeadless(new AvaloniaHeadlessPlatformOptions());
}

internal static class VisualTreeHelpers
{
    /// <summary>Recursively finds the first descendant with the given x:Name.</summary>
    public static Control? FindDescendantByName(this Control root, string name)
    {
        if (root.Name == name) return root;
        foreach (var child in root.GetVisualDescendants<Control>())
        {
            if (child.Name == name) return child;
        }
        return null;
    }

    private static IEnumerable<T> GetVisualDescendants<T>(this Avalonia.Visual visual)
        where T : Avalonia.Visual
    {
        foreach (var child in visual.GetVisualChildren())
        {
            if (child is T typed) yield return typed;
            foreach (var grand in child.GetVisualDescendants<T>())
                yield return grand;
        }
    }
}
