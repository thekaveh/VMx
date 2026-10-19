using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Headless.XUnit;
using Avalonia.Threading;
using Avalonia.VisualTree;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views;
using NotesShowcase.Views.Adapter;
using VMx.Dialogs;
using VMx.Notifications;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.Views;

/// <summary>
/// Drives the real <see cref="MainWindow"/> headlessly to pin that list/tree
/// refreshes never drop the current selection through the views' TwoWay
/// <c>SelectedItem</c> bindings (selection must survive a refilter or a
/// notebook add, as in the React, Textual, and Rust flagships).
/// </summary>
public sealed class SelectionStabilityHeadlessTests
{
    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task Refiltering_the_notes_list_keeps_the_selected_note_and_its_draft()
    {
        var (workspace, window) = await OpenWindowAsync();
        try
        {
            var list = (ListBox)window.FindDescendantByName("NotesList")!;
            var search = (TextBox)window.FindDescendantByName("SearchInput")!;
            var titleBox = window.GetVisualDescendants().OfType<TextBox>()
                .Single(t => AutomationProperties.GetName(t) == "Note title");

            // User clicks the second note of the bound notebook.
            var note = workspace.NotesView.VisibleItems
                .Single(n => n.Title == "Roadmap snapshot");
            list.SelectedItem = note;
            Pump();
            Assert.Same(note, workspace.NotesView.Current);
            Assert.True(workspace.NoteForm.HasBoundNote);

            // User edits the title (unsaved draft).
            titleBox.Text = "Roadmap snapshot (draft)";
            Pump();
            Assert.True(workspace.NoteForm.IsDirty);

            // Typing a search the note still matches refilters the list.
            search.Text = "Roadmap";
            PumpUntil(() => workspace.NotesView.VisibleItems.Count == 1);
            AssertSelectionAndDraftKept(workspace, list, note);

            // Clearing the search refilters again.
            search.Text = string.Empty;
            PumpUntil(() => workspace.NotesView.VisibleItems.Count == 2);
            AssertSelectionAndDraftKept(workspace, list, note);

            // Ctrl+S (save) re-runs the filter via RefreshNote.
            workspace.NoteForm.ApproveCommand.Execute(null);
            PumpUntil(() => !workspace.NoteForm.IsDirty);
            Pump();
            Assert.Same(note, workspace.NotesView.Current);
            Assert.Same(note, list.SelectedItem);
            Assert.True(workspace.NoteForm.HasBoundNote);
            Assert.Equal("Roadmap snapshot (draft)", workspace.NoteForm.Title);
        }
        finally
        {
            workspace.Dispose();
            window.Close();
        }
    }

    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task Adding_a_notebook_keeps_the_selected_notebook_and_New_Note_enabled()
    {
        var (workspace, window) = await OpenWindowAsync();
        try
        {
            var tree = (TreeView)window.FindDescendantByName("NotebooksTree")!;
            var selected = workspace.NotebooksRoot.Current;
            Assert.NotNull(selected);
            Assert.Same(selected, tree.SelectedItem);
            Assert.True(workspace.NewNoteCommand.CanExecute(null));

            // User clicks "+ Notebook".
            var addNotebook = window.GetVisualDescendants().OfType<Button>()
                .Single(b => Equals(b.Content, "+ Notebook"));
            var before = workspace.NotebooksRoot.All.Count;
            addNotebook.Command!.Execute(addNotebook.CommandParameter);
            PumpUntil(() => workspace.NotebooksRoot.Roots.Count == 5
                && workspace.NotebooksRoot.All.Count == before + 1);
            Pump();

            Assert.Same(selected, workspace.NotebooksRoot.Current);
            Assert.Same(selected, tree.SelectedItem);
            Assert.True(workspace.NewNoteCommand.CanExecute(null));
        }
        finally
        {
            workspace.Dispose();
            window.Close();
        }
    }

    private static void AssertSelectionAndDraftKept(WorkspaceVM workspace, ListBox list, NoteVM note)
    {
        Assert.Same(note, workspace.NotesView.Current);
        Assert.Same(note, list.SelectedItem);
        Assert.True(workspace.NoteForm.HasBoundNote);
        Assert.True(workspace.NoteForm.IsDirty);
        Assert.Equal("Roadmap snapshot (draft)", workspace.NoteForm.Title);
    }

    private static async Task<(WorkspaceVM Workspace, MainWindow Window)> OpenWindowAsync()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            deleteNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero,
            exportDelay: TimeSpan.Zero);
        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(NullDialogService.Instance)
            .NotificationHub(new NotificationHub())
            .MessageHub(new MessageHub())
            .Dispatcher(new AvaloniaDispatcher())
            .Build();
        // Same ordering as the real App: start the async construct, bind the
        // window before it completes, then let it finish.
        var construct = workspace.ConstructAsync();
        var window = new MainWindow { DataContext = workspace };
        window.Show();
        window.UpdateLayout();
        await construct;
        PumpUntil(() => workspace.NotebooksRoot.Current is not null
            && workspace.NotesView.VisibleItems.Count > 0);
        Pump();
        window.UpdateLayout();
        return (workspace, window);
    }

    private static void Pump()
    {
        Dispatcher.UIThread.RunJobs();
    }

    private static void PumpUntil(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(5);
        while (true)
        {
            Dispatcher.UIThread.RunJobs();
            if (condition()) return;
            Assert.True(DateTime.UtcNow < deadline, "Timed out waiting for the UI to settle.");
            Thread.Sleep(10);
        }
    }
}
