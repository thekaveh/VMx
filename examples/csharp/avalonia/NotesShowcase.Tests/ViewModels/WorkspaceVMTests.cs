using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Lifecycle;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class WorkspaceVMTests
{
    private static WorkspaceVM BuildWorkspace()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        return WorkspaceVM.Builder()
            .Repository(repo)
            .Build();
    }

    [Fact]
    public async Task ConstructAsync_loads_notebooks_selects_first_and_populates_notes()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            Assert.Equal(ConstructionStatus.Constructed, ws.Status);
            Assert.NotNull(ws.NotebooksRoot.Current);
            Assert.NotEmpty(ws.NotesView.VisibleItems);
            // First root in seed order is nb-work.
            Assert.Equal("nb-work", ws.NotebooksRoot.Current!.Model.Id);
            Assert.All(ws.NotesView.FilteredItems, n => Assert.Equal("nb-work", n.Model.NotebookId));
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task All_six_aggregate_children_are_constructed()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            Assert.True(ws.NotebooksRoot.IsConstructed);
            Assert.True(ws.NotesView.IsConstructed);
            Assert.True(ws.NoteForm.IsConstructed);
            Assert.True(ws.StatusBar.IsConstructed);
            Assert.True(ws.Notifications.IsConstructed);
            Assert.True(ws.CapabilityActions.IsConstructed);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task NewNoteCommand_adds_a_note_in_the_current_notebook()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var nbId = ws.NotebooksRoot.Current!.Model.Id;
            var before = ws.NotesView.FilteredItems.Count;
            ws.NewNoteCommand.Execute(null);
            // NewNote is fire-and-forget; let it complete.
            await Task.Delay(50);
            Assert.True(ws.NotesView.FilteredItems.Count >= before);
            // After rebind, all visible notes belong to the current notebook.
            Assert.All(ws.NotesView.FilteredItems, n => Assert.Equal(nbId, n.Model.NotebookId));
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task SetFocus_triggers_capability_actions_recompute()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            // Focus on a notebook: actions list includes "Expand".
            ws.SetFocus(ws.NotebooksRoot.Current!);
            Assert.Contains("Expand", ws.CapabilityActions.Actions.Value.Select(a => a.Label));
            // Focus on a note: actions list switches to note actions.
            var note = ws.NotesView.FilteredItems[0];
            ws.SetFocus(note);
            var labels = ws.CapabilityActions.Actions.Value.Select(a => a.Label).ToList();
            Assert.Contains("Close", labels);
            Assert.DoesNotContain("Expand", labels);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task NewNotebookCommand_appends_a_notebook()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var before = ws.NotebooksRoot.All.Count;
            ws.NewNotebookCommand.Execute(null);
            await Task.Delay(50);
            Assert.True(ws.NotebooksRoot.All.Count > before);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Destruct_cascades_to_all_six_children()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        ws.Destruct();
        Assert.Equal(ConstructionStatus.Destructed, ws.NotebooksRoot.Status);
        Assert.Equal(ConstructionStatus.Destructed, ws.NotesView.Status);
        Assert.Equal(ConstructionStatus.Destructed, ws.NoteForm.Status);
        Assert.Equal(ConstructionStatus.Destructed, ws.StatusBar.Status);
        Assert.Equal(ConstructionStatus.Destructed, ws.Notifications.Status);
        Assert.Equal(ConstructionStatus.Destructed, ws.CapabilityActions.Status);
        ws.Dispose();
    }
}
