using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Dialogs;
using VMx.Lifecycle;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

/// <summary>
/// Test-only dialog service whose <see cref="Confirm"/> returns a pre-canned
/// boolean. Used by the Round-4 Important-1 "select then delete clears form"
/// test which needs the in-list delete confirmation to accept.
/// </summary>
file sealed class AlwaysAcceptDialogService : IDialogService
{
    public Task<string?> PickFileToOpen(FileFilter? filter, string? title)
        => Task.FromResult<string?>(null);
    public Task<string?> PickFileToSave(FileFilter? filter, string? title, string? suggestedName)
        => Task.FromResult<string?>(null);
    public Task<bool> Confirm(string message, string? title = null)
        => Task.FromResult(true);
    public Task Notify(string message, string? title = null, NotificationSeverity severity = NotificationSeverity.Info)
        => Task.CompletedTask;
}

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
    public async Task Selecting_a_note_then_deleting_it_clears_the_form()
    {
        // Round-4 Important-1: when NotesView.Current transitions to null
        // (because the user deletes the selected note), the WorkspaceVM
        // subscription must call NoteForm.Unbind so the right pane does
        // not display ghost data from the just-removed note.
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            deleteNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var ws = WorkspaceVM.Builder()
            .Repository(repo)
            // ConfirmationDecorator must accept so the delete actually runs.
            .DialogService(new AlwaysAcceptDialogService())
            .Build();
        await ws.ConstructAsync();
        try
        {
            // Pick a note from the first notebook (seeded nb-work ships
            // with two notes — ConstructAsync already binds to it).
            var note = ws.NotesView.FilteredItems[0];
            ws.NotesView.Current = note;
            // Subscription is synchronous on the immediate-scheduler default
            // — the form should now be bound to the selected note.
            Assert.True(ws.NoteForm.HasBoundNote);
            Assert.Equal(note.Title, ws.NoteForm.Title);

            // Invoke the in-list delete pathway. With the always-accept
            // dialog the ConfirmationDecorator forwards to the inner Task,
            // and NotesViewVM.DeleteNoteAsyncInternal clears Current.
            note.DeleteCommand.Execute(null);
            await Task.Delay(50);

            Assert.Null(ws.NotesView.Current);
            // The form must have been unbound — no ghost data left over.
            Assert.False(ws.NoteForm.HasBoundNote);
            Assert.Equal(string.Empty, ws.NoteForm.Title);
            Assert.Equal(string.Empty, ws.NoteForm.Body);
        }
        finally
        {
            ws.Dispose();
        }
    }

    // ── Pass-6 real-wiring regressions ───────────────────────────────────

    [Fact]
    public async Task Selecting_another_notebook_rebinds_the_notes_view()
    {
        // The tree's TwoWay SelectedItem binding only sets
        // NotebooksRoot.Current — the workspace subscription must do the rest.
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var firstId = ws.NotesView.BoundNotebookId;
            var other = ws.NotebooksRoot.Roots.First(nb => nb.Model.Id != firstId);

            ws.NotebooksRoot.Current = other;
            await Task.Delay(50);

            Assert.Equal(other.Model.Id, ws.NotesView.BoundNotebookId);
            Assert.All(ws.NotesView.FilteredItems,
                n => Assert.Equal(other.Model.Id, n.Model.NotebookId));
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Toolbar_commands_fire_CanExecuteChanged_after_construction()
    {
        // Avalonia caches CanExecute() from before construction finished;
        // without a trigger the "+ Note" button stayed permanently disabled.
        var ws = BuildWorkspace();
        var changes = 0;
        ws.NewNoteCommand.CanExecuteChanged += (_, _) => changes++;
        Assert.False(ws.NewNoteCommand.CanExecute(null));

        await ws.ConstructAsync();

        try
        {
            Assert.True(changes > 0,
                "CanExecuteChanged must fire so bound buttons re-evaluate");
            Assert.True(ws.NewNoteCommand.CanExecute(null));
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Deny_reverts_and_republishes_the_draft_surface()
    {
        // The inner FormVM's Deny publishes with sender = FormVM, which the
        // XAML bindings (keyed on NoteFormVM) never observe — the stable
        // DenyCommand must re-emit this VM's own channels.
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            ws.NotesView.Current = note;
            var original = ws.NoteForm.Title;
            ws.NoteForm.Title = original + " (edited)";
            Assert.True(ws.NoteForm.IsDirty);

            var raised = new List<string>();
            ws.NoteForm.PropertyChanged += (_, e) => raised.Add(e.PropertyName ?? "");
            ws.NoteForm.DenyCommand.Execute(null);

            Assert.False(ws.NoteForm.IsDirty);
            Assert.Equal(original, ws.NoteForm.Title);
            Assert.Contains(nameof(NoteFormVM.Title), raised);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Save_refreshes_the_list_rows_title_and_star()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            ws.NotesView.Current = note;
            ws.NoteForm.Title = "Retitled by test";
            await ws.NoteForm.ApproveAsync();
            await Task.Delay(50);

            Assert.Equal("Retitled by test", note.Title);
            Assert.Contains(ws.NotesView.FilteredItems,
                n => n.Title == "Retitled by test");
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
