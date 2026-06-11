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
    public async Task Editing_NoteFormVM_Title_Flips_Dirty_And_Enables_Save()
    {
        // End-to-end Phase 5.a binding gap #1: the two-way bound TextBox on
        // NoteFormView pushes edits through ``NoteFormVM.Title``; that flips
        // IsDirty and re-fires ApproveCommand.CanExecuteChanged so the Save
        // button enables. We assert the VM-level surface here (the XAML
        // binding mode is exercised by Avalonia's binding engine in the
        // real app — see plan §5.a.headless).
        var seed = SeedData.Build();
        var repo = new InMemoryNoteRepository(
            seed,
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var hub = new MessageHub();
        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(NullDialogService.Instance)
            .NotificationHub(new NotificationHub())
            .MessageHub(hub)
            .Dispatcher(new AvaloniaDispatcher())
            .Build();
        await workspace.ConstructAsync();

        var note = (await repo.LoadAllAsync()).Notes.First();
        workspace.NoteForm.BindTo(note);
        Assert.False(workspace.NoteForm.IsDirty);
        Assert.False(workspace.NoteForm.ApproveCommand.CanExecute(null));

        // Simulate the two-way bound TextBox writing back through the
        // scalar Title setter.
        var canExecuteChanges = 0;
        workspace.NoteForm.ApproveCommand.CanExecuteChanged += (_, _) => canExecuteChanges++;
        workspace.NoteForm.Title = note.Title + " (edited)";

        Assert.True(workspace.NoteForm.IsDirty);
        Assert.True(workspace.NoteForm.ApproveCommand.CanExecute(null));
        Assert.True(canExecuteChanges > 0, "ApproveCommand.CanExecuteChanged must fire so XAML re-evaluates the Save button.");

        await workspace.NoteForm.ApproveAsync();
        Assert.False(workspace.NoteForm.IsDirty);
        Assert.EndsWith("(edited)", workspace.NoteForm.Snapshot.Title);

        workspace.Dispose();
    }

    // ── Round-3 Critical-2: WorkspaceVM observes NotesView.Current changes
    // and re-binds NoteForm — without this the right-pane editor stays
    // empty when the user clicks a note in the centre pane.
    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task Selecting_a_note_in_NotesView_Current_rebinds_NoteForm()
    {
        var seed = SeedData.Build();
        var repo = new InMemoryNoteRepository(
            seed,
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var hub = new MessageHub();
        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(NullDialogService.Instance)
            .NotificationHub(new NotificationHub())
            .MessageHub(hub)
            .Dispatcher(new AvaloniaDispatcher())
            .Build();
        await workspace.ConstructAsync();
        Assert.False(workspace.NoteForm.HasBoundNote);

        // Bind the notes view to a notebook with notes and select one.
        await workspace.NotesView.BindToAsync("nb-personal");
        var first = workspace.NotesView.Inner[0];
        workspace.NotesView.Current = first;

        // Round-4 Important-2: the WorkspaceVM subscription now uses
        // ObserveOn(_dispatcher.Foreground), so the BindTo handler is
        // queued onto Dispatcher.UIThread instead of running inline.
        // Drain the UI dispatcher so the queued post executes.
        Avalonia.Threading.Dispatcher.UIThread.RunJobs();

        // The WorkspaceVM subscription should have rebound the form.
        Assert.True(workspace.NoteForm.HasBoundNote);
        Assert.Equal(first.Title, workspace.NoteForm.Title);
        Assert.Equal(first.Body, workspace.NoteForm.Body);

        workspace.Dispose();
    }

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

        // NOTE: this smoke test binds after construct, so it covers the view
        // plumbing only. The real App binds BEFORE ConstructAsync completes;
        // that ordering depends on the Roots PropertyChanged raise, which is
        // pinned by NotebooksRootVMTests.PopulateAsync_raises_PropertyChanged
        // _for_Roots (the raise was missing and this test masked it).
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
