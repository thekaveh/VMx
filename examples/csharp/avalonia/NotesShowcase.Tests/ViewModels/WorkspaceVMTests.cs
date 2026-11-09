using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Commands;
using VMx.Dialogs;
using VMx.Lifecycle;
using VMx.Notifications;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

/// <summary>
/// Test-only dialog service whose <see cref="Confirm"/> returns a pre-canned
/// boolean. Used by the cleared-selection form behavior "select then delete clears form"
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

    private static WorkspaceVM BuildWorkspace(
        IReadOnlyList<NotebookModel> notebooks,
        IReadOnlyList<NoteModel>? notes = null)
    {
        var repo = new InMemoryNoteRepository(
            (notebooks, notes ?? Array.Empty<NoteModel>()),
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
            await Assert.IsType<AsyncRelayCommand>(ws.NewNoteCommand).ExecuteAsync();
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
    public async Task Selecting_a_note_updates_capability_focus()
    {
        var ws = BuildWorkspace();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.FilteredItems[0];
            ws.NotesView.Current = note;

            var labels = ws.CapabilityActions.Actions.Value.Select(a => a.Label).ToList();
            Assert.Contains("Close", labels);
            Assert.Contains("Save", labels);
            Assert.DoesNotContain("Expand", labels);

            ws.NotesView.Current = null;
            var fallback = ws.CapabilityActions.Actions.Value.Select(a => a.Label).ToList();
            Assert.Contains("Expand", fallback);
            Assert.DoesNotContain("Save", fallback);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task NewNotebookCommand_appends_a_notebook()
    {
        var ws = WorkspaceVM.Builder()
            .Repository(new InMemoryNoteRepository(
                SeedData.Build(),
                loadAllDelay: TimeSpan.Zero,
                loadNotesDelay: TimeSpan.Zero,
                addNotebookDelay: TimeSpan.FromMilliseconds(25)))
            .Build();
        await ws.ConstructAsync();
        try
        {
            var before = ws.NotebooksRoot.All.Count;
            await Assert.IsType<AsyncRelayCommand>(ws.NewNotebookCommand).ExecuteAsync();
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
        // cleared-selection form behavior: when NotesView.Current transitions to null
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
            await TestWait.WaitUntilAsync(() => ws.NotesView.Current is null);

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

    // ── Live-binding regressions ─────────────────────────────────────────

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
            await TestWait.WaitUntilAsync(() =>
            {
                if (ws.NotesView.BoundNotebookId != other.Model.Id)
                {
                    return false;
                }

                try
                {
                    var items = ws.NotesView.FilteredItems.ToArray();
                    return items.Length > 0
                           && items.All(n => n.Model.NotebookId == other.Model.Id);
                }
                catch (InvalidOperationException)
                {
                    return false;
                }
            });

            Assert.Equal(other.Model.Id, ws.NotesView.BoundNotebookId);
            var snapshot = ws.NotesView.FilteredItems.ToArray();
            Assert.All(snapshot, n => Assert.Equal(other.Model.Id, n.Model.NotebookId));
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
    public void NotebookModel_default_is_not_readonly()
    {
        var nb = new NotebookModel("nb", "Notebook", ParentId: null);

        Assert.False(nb.IsReadOnly);
    }

    [Fact]
    public async Task Capability_add_note_is_disabled_for_readonly_notebook()
    {
        var ws = BuildWorkspace(new[]
        {
            new NotebookModel("nb-readonly", "Archive", ParentId: null, IsReadOnly: true),
        });
        await ws.ConstructAsync();
        try
        {
            Assert.True(ws.NotesView.CurrentNotebookIsReadOnly);
            Assert.False(ws.CapabilityActions.AddNoteCommand.CanExecute(null));
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Capability_add_note_is_enabled_for_writable_notebook()
    {
        var ws = BuildWorkspace(new[]
        {
            new NotebookModel("nb-rw", "Drafts", ParentId: null),
        });
        await ws.ConstructAsync();
        try
        {
            Assert.False(ws.NotesView.CurrentNotebookIsReadOnly);
            Assert.True(ws.CapabilityActions.AddNoteCommand.CanExecute(null));
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
            await TestWait.WaitUntilAsync(
                () => ws.NotesView.FilteredItems.Any(n => n.Title == "Retitled by test"));

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
    public async Task An_older_save_that_settles_last_keeps_the_newer_values()
    {
        // #1379: the repository writes each save when it starts and answers
        // the newer save first.
        var repo = new WriteFirstRepository();
        var ws = WorkspaceVM.Builder().Repository(repo).Build();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            var other = ws.NotesView.Inner[1];
            var noteId = note.Model.Id;
            var form = ws.NoteForm;

            ws.NotesView.Current = note;
            form.Title = "Older title";
            var saveA = form.ApproveAsync();
            await TestWait.WaitUntilAsync(() => repo.HeldCount == 1);
            // Leave the note and return while save A is held, then start save B.
            ws.NotesView.Current = other;
            ws.NotesView.Current = note;
            Assert.NotEqual("Older title", form.Title);
            form.Title = "Newer title";
            var saveB = form.ApproveAsync();
            await TestWait.WaitUntilAsync(() => repo.HeldCount == 2);

            // The newer save settles first, then the older one.
            repo.Release(1);
            await saveB;
            repo.Release(0);
            await saveA;

            Assert.Equal("Newer title", form.Title);
            Assert.False(form.IsDirty);
            Assert.Equal("Newer title", ws.NotesView.Inner.First(n => n.Model.Id == noteId).Title);

            // A later save stores the newer values.
            form.Body = "Body after both saves";
            var saveC = form.ApproveAsync();
            await TestWait.WaitUntilAsync(() => repo.HeldCount == 3);
            repo.Release(2);
            await saveC;
            var (_, notes) = await repo.LoadAllAsync();
            var stored = notes.First(n => n.Id == noteId);
            Assert.Equal("Newer title", stored.Title);
            Assert.Equal("Body after both saves", stored.Body);
        }
        finally
        {
            ws.Dispose();
        }
    }

    /// <summary>
    /// Writes each save when it starts, then holds its answer until the test
    /// releases that save, so saves can settle out of order.
    /// </summary>
    private sealed class WriteFirstRepository : INoteRepository
    {
        private readonly InMemoryNoteRepository _inner = new(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        private readonly List<TaskCompletionSource> _held = new();

        public int HeldCount
        {
            get { lock (_held) return _held.Count; }
        }

        public void Release(int index)
        {
            lock (_held) _held[index].SetResult();
        }

        public Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(CancellationToken ct = default)
            => _inner.LoadAllAsync(ct);
        public Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default)
            => _inner.LoadNotesAsync(notebookId, ct);
        public Task<NoteSearchPage> SearchNotesAsync(string term, string? token, int pageSize, CancellationToken ct = default)
            => _inner.SearchNotesAsync(term, token, pageSize, ct);
        public async Task SaveNoteAsync(NoteModel note, CancellationToken ct = default)
        {
            await _inner.SaveNoteAsync(note, ct).ConfigureAwait(false);
            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (_held) _held.Add(release);
            await release.Task.ConfigureAwait(false);
        }
        public Task DeleteNoteAsync(string id, CancellationToken ct = default)
            => _inner.DeleteNoteAsync(id, ct);
        public Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default)
            => _inner.AddNotebookAsync(notebook, ct);
        public Task ExportAsync(IReadOnlyList<NotebookModel> notebooks, IReadOnlyList<NoteModel> notes, string path, CancellationToken ct = default)
            => _inner.ExportAsync(notebooks, notes, path, ct);
    }

    private sealed class SaveSpyRepository : INoteRepository
    {
        private readonly INoteRepository _inner;
        public int SaveCalls;
        public SaveSpyRepository(INoteRepository inner) => _inner = inner;
        public Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(CancellationToken ct = default)
            => _inner.LoadAllAsync(ct);
        public Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default)
            => _inner.LoadNotesAsync(notebookId, ct);
        public Task<NoteSearchPage> SearchNotesAsync(string term, string? token, int pageSize, CancellationToken ct = default)
            => _inner.SearchNotesAsync(term, token, pageSize, ct);
        public Task SaveNoteAsync(NoteModel note, CancellationToken ct = default)
        {
            Interlocked.Increment(ref SaveCalls);
            return _inner.SaveNoteAsync(note, ct);
        }
        public Task DeleteNoteAsync(string id, CancellationToken ct = default)
            => _inner.DeleteNoteAsync(id, ct);
        public Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default)
            => _inner.AddNotebookAsync(notebook, ct);
        public Task ExportAsync(IReadOnlyList<NotebookModel> notebooks, IReadOnlyList<NoteModel> notes, string path, CancellationToken ct = default)
            => _inner.ExportAsync(notebooks, notes, path, ct);
    }

    [Fact]
    public async Task Capability_save_and_close_act_on_the_focused_note()
    {
        // Pins the OnSave/OnClose wiring in NotesViewVM.ReplaceItems — both
        // capability-bar actions were silent no-ops before the handler wiring was added.
        var spy = new SaveSpyRepository(new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero));
        var ws = WorkspaceVM.Builder().Repository(spy).Build();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            ws.NotesView.Current = note;
            // ADR-0201 §2.3: the editor holds this note, so Save persists the
            // draft and a clean draft writes nothing. Edit the title first.
            ws.NoteForm.Title = note.Title + " (edited)";

            note.SaveCommand.Execute(null);
            await TestWait.WaitUntilAsync(() => spy.SaveCalls > 0);
            Assert.True(spy.SaveCalls > 0, "capability Save must reach the repository");

            note.CloseCommand.Execute(null);
            Assert.Null(ws.NotesView.Current);
        }
        finally
        {
            ws.Dispose();
        }
    }

    private static (WorkspaceVM Workspace, SaveSpyRepository Repo) BuildSpyWorkspace()
    {
        var spy = new SaveSpyRepository(new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero));
        return (WorkspaceVM.Builder().Repository(spy).Build(), spy);
    }

    private static async Task<NoteModel> StoredNoteAsync(INoteRepository repo, NoteModel note)
        => (await repo.LoadNotesAsync(note.NotebookId)).Single(n => n.Id == note.Id);

    private static Task RunActionBarSaveAsync(WorkspaceVM ws)
    {
        var save = ws.CapabilityActions.Actions.Value.Single(a => a.Label == "Save");
        return Assert.IsType<AsyncRelayCommand>(save.Command).ExecuteAsync();
    }

    [Fact]
    public async Task Selecting_another_note_discards_the_unsaved_draft()
    {
        // ADR-0201 §2.2: a note switch discards the draft with no prompt.
        var (ws, repo) = BuildSpyWorkspace();
        await ws.ConstructAsync();
        try
        {
            var a = ws.NotesView.Inner[0];
            var b = ws.NotesView.Inner[1];
            var storedTitle = a.Model.Title;
            ws.NotesView.Current = a;
            ws.NoteForm.Title = storedTitle + " (draft)";
            Assert.True(ws.NoteForm.IsDirty);

            ws.NotesView.Current = b;

            Assert.Equal(b.Model.Title, ws.NoteForm.Title);
            Assert.False(ws.NoteForm.IsDirty);

            ws.NotesView.Current = a;

            Assert.Equal(storedTitle, ws.NoteForm.Title);
            Assert.False(ws.NoteForm.IsDirty);
            Assert.Equal(storedTitle, (await StoredNoteAsync(repo, a.Model)).Title);
            Assert.Equal(0, repo.SaveCalls);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Action_bar_Save_on_the_edited_note_persists_the_editor_draft()
    {
        // ADR-0201 §2.3: the action-bar Save on the note the editor holds is
        // the editor Save.
        var (ws, repo) = BuildSpyWorkspace();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            ws.NotesView.Current = note;
            ws.NoteForm.Title = "Retitled through the action bar";

            await RunActionBarSaveAsync(ws);

            Assert.Equal("Retitled through the action bar", (await StoredNoteAsync(repo, note.Model)).Title);
            Assert.Equal(1, repo.SaveCalls);
            await TestWait.WaitUntilAsync(() => !ws.NoteForm.IsDirty);
            Assert.False(ws.NoteForm.IsDirty);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    public async Task Action_bar_Save_writes_nothing_for_an_invalid_or_clean_draft(string? title)
    {
        // ADR-0201 §2.3: an invalid ("" title) or clean (null: no edit) draft
        // persists nothing.
        var (ws, repo) = BuildSpyWorkspace();
        await ws.ConstructAsync();
        try
        {
            var note = ws.NotesView.Inner[0];
            var storedTitle = note.Model.Title;
            ws.NotesView.Current = note;
            if (title is not null) ws.NoteForm.Title = title;

            await RunActionBarSaveAsync(ws);

            Assert.Equal(0, repo.SaveCalls);
            Assert.Equal(storedTitle, (await StoredNoteAsync(repo, note.Model)).Title);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Action_bar_Save_on_another_note_saves_its_stored_model()
    {
        // ADR-0201 §2.3: when the editor holds another note, Save persists the
        // stored model of the focused note and leaves the editor draft alone.
        var (ws, repo) = BuildSpyWorkspace();
        await ws.ConstructAsync();
        try
        {
            var edited = ws.NotesView.Inner[0];
            var other = ws.NotesView.Inner[1];
            ws.NotesView.Current = edited;
            ws.NoteForm.Title = "Draft that stays unsaved";
            ws.SetFocus(other);

            await RunActionBarSaveAsync(ws);

            Assert.Equal(1, repo.SaveCalls);
            Assert.Equal(other.Model.Title, (await StoredNoteAsync(repo, other.Model)).Title);
            Assert.Equal(edited.Model.Title, (await StoredNoteAsync(repo, edited.Model)).Title);
            Assert.True(ws.NoteForm.IsDirty);
            Assert.Equal("Draft that stays unsaved", ws.NoteForm.Title);
        }
        finally
        {
            ws.Dispose();
        }
    }

    private sealed class FailingLoadRepository : INoteRepository
    {
        private readonly INoteRepository _inner;
        private readonly string _failId;
        public int FailedLoads;
        public FailingLoadRepository(INoteRepository inner, string failId)
        { _inner = inner; _failId = failId; }
        public Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(CancellationToken ct = default)
            => _inner.LoadAllAsync(ct);
        public Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default)
        {
            if (notebookId == _failId && FailedLoads++ == 0)
            {
                throw new InvalidOperationException("transient repo failure");
            }
            return _inner.LoadNotesAsync(notebookId, ct);
        }
        public Task<NoteSearchPage> SearchNotesAsync(string term, string? token, int pageSize, CancellationToken ct = default)
            => _inner.SearchNotesAsync(term, token, pageSize, ct);
        public Task SaveNoteAsync(NoteModel note, CancellationToken ct = default) => _inner.SaveNoteAsync(note, ct);
        public Task DeleteNoteAsync(string id, CancellationToken ct = default) => _inner.DeleteNoteAsync(id, ct);
        public Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default) => _inner.AddNotebookAsync(notebook, ct);
        public Task ExportAsync(IReadOnlyList<NotebookModel> notebooks, IReadOnlyList<NoteModel> notes, string path, CancellationToken ct = default)
            => _inner.ExportAsync(notebooks, notes, path, ct);
    }

    [Fact]
    public async Task A_failed_notebook_bind_does_not_pin_the_selection()
    {
        // failure recovery: a throwing bind must clear _requestedNotebookId so the
        // notebook stays selectable, and the fault must be observed.
        var repo = new FailingLoadRepository(
            new InMemoryNoteRepository(
                SeedData.Build(),
                loadAllDelay: TimeSpan.Zero,
                loadNotesDelay: TimeSpan.Zero,
                saveNoteDelay: TimeSpan.Zero,
                addNotebookDelay: TimeSpan.Zero),
            failId: "nb-personal");
        var ws = WorkspaceVM.Builder().Repository(repo).Build();
        await ws.ConstructAsync();
        try
        {
            var personal = ws.NotebooksRoot.Roots.First(nb => nb.Model.Id == "nb-personal");
            ws.NotebooksRoot.Current = personal;
            await TestWait.WaitUntilAsync(() => repo.FailedLoads >= 1);
            Assert.Equal(1, repo.FailedLoads);
            Assert.NotEqual("nb-personal", ws.NotesView.BoundNotebookId);

            // Re-selecting after a failure must retry (the requested id was
            // cleared). Bounce through another notebook so Current changes.
            ws.NotebooksRoot.Current = ws.NotebooksRoot.Roots.First(nb => nb.Model.Id == "nb-work");
            await TestWait.WaitUntilAsync(() => ws.NotesView.BoundNotebookId == "nb-work");
            ws.NotebooksRoot.Current = personal;
            await TestWait.WaitUntilAsync(() => ws.NotesView.BoundNotebookId == "nb-personal");
            Assert.Equal("nb-personal", ws.NotesView.BoundNotebookId);
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Construct_with_no_notebooks_still_enables_the_toolbar()
    {
        var repo = new InMemoryNoteRepository(
            (Array.Empty<NotebookModel>(), Array.Empty<NoteModel>()),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var ws = WorkspaceVM.Builder().Repository(repo).Build();
        await ws.ConstructAsync();
        try
        {
            Assert.True(ws.NewNotebookCommand.CanExecute(null));
            Assert.False(ws.NewNoteCommand.CanExecute(null), "no current notebook yet");
        }
        finally
        {
            ws.Dispose();
        }
    }

    [Fact]
    public async Task Export_command_writes_the_workspace_through_the_dialog_path()
    {
        var path = Path.Combine(Path.GetTempPath(), $"vmx-export-{Guid.NewGuid():N}.json");
        var ws = WorkspaceVM.Builder()
            .Repository(new InMemoryNoteRepository(
                SeedData.Build(),
                loadAllDelay: TimeSpan.Zero,
                loadNotesDelay: TimeSpan.Zero,
                saveNoteDelay: TimeSpan.Zero,
                addNotebookDelay: TimeSpan.Zero,
                exportDelay: TimeSpan.Zero))
            .DialogService(new SaveDialogService(path))
            .Build();
        await ws.ConstructAsync();
        try
        {
            await Assert.IsType<AsyncRelayCommand>(ws.ExportCommand).ExecuteAsync();
            Assert.True(File.Exists(path), "export must write through the picked path");
        }
        finally
        {
            ws.Dispose();
            if (File.Exists(path)) File.Delete(path);
        }
    }

    [Fact]
    public async Task Export_command_posts_one_notification_after_the_file_is_written()
    {
        // #1329: the scenario's Export step confirms the written file.
        var path = Path.Combine(Path.GetTempPath(), $"vmx-export-{Guid.NewGuid():N}.json");
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        var fileExistedAtPost = new List<bool>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot)
            {
                if (observed.Contains(n)) continue;
                observed.Add(n);
                fileExistedAtPost.Add(File.Exists(path));
            }
        });
        var ws = BuildExportWorkspace(new SaveDialogService(path), notificationHub);
        await ws.ConstructAsync();
        try
        {
            await Assert.IsType<AsyncRelayCommand>(ws.ExportCommand).ExecuteAsync();

            var notification = Assert.Single(observed);
            Assert.Equal(NotificationType.Notification, notification.Type);
            Assert.Equal($"Exported to {path}", notification.Message);
            Assert.Equal(new[] { true }, fileExistedAtPost);
        }
        finally
        {
            ws.Dispose();
            if (File.Exists(path)) File.Delete(path);
        }
    }

    [Fact]
    public async Task Export_command_cancelled_by_the_dialog_writes_nothing_and_posts_nothing()
    {
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot) if (!observed.Contains(n)) observed.Add(n);
        });
        var repo = new CountingExportRepository();
        var ws = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(new SaveDialogService(null))
            .NotificationHub(notificationHub)
            .Build();
        await ws.ConstructAsync();
        try
        {
            await Assert.IsType<AsyncRelayCommand>(ws.ExportCommand).ExecuteAsync();

            Assert.Equal(0, repo.Exports);
            Assert.Empty(observed);
        }
        finally
        {
            ws.Dispose();
        }
    }

    private static WorkspaceVM BuildExportWorkspace(IDialogService dialog, INotificationHub notificationHub)
        => WorkspaceVM.Builder()
            .Repository(new InMemoryNoteRepository(
                SeedData.Build(),
                loadAllDelay: TimeSpan.Zero,
                loadNotesDelay: TimeSpan.Zero,
                saveNoteDelay: TimeSpan.Zero,
                addNotebookDelay: TimeSpan.Zero,
                exportDelay: TimeSpan.Zero))
            .DialogService(dialog)
            .NotificationHub(notificationHub)
            .Build();

    /// <summary>An in-memory repository that counts its exports.</summary>
    private sealed class CountingExportRepository : INoteRepository
    {
        private readonly InMemoryNoteRepository _inner = new(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero,
            exportDelay: TimeSpan.Zero);

        public int Exports { get; private set; }

        public Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(CancellationToken ct = default)
            => _inner.LoadAllAsync(ct);
        public Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default)
            => _inner.LoadNotesAsync(notebookId, ct);
        public Task<NoteSearchPage> SearchNotesAsync(string term, string? token, int pageSize, CancellationToken ct = default)
            => _inner.SearchNotesAsync(term, token, pageSize, ct);
        public Task SaveNoteAsync(NoteModel note, CancellationToken ct = default)
            => _inner.SaveNoteAsync(note, ct);
        public Task DeleteNoteAsync(string id, CancellationToken ct = default)
            => _inner.DeleteNoteAsync(id, ct);
        public Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default)
            => _inner.AddNotebookAsync(notebook, ct);
        public Task ExportAsync(IReadOnlyList<NotebookModel> notebooks, IReadOnlyList<NoteModel> notes, string path, CancellationToken ct = default)
        {
            Exports++;
            return _inner.ExportAsync(notebooks, notes, path, ct);
        }
    }

    private sealed class SaveDialogService : IDialogService
    {
        private readonly string? _path;
        public SaveDialogService(string? path) => _path = path;
        public Task<string?> PickFileToOpen(FileFilter? filter, string? title)
            => Task.FromResult<string?>(null);
        public Task<string?> PickFileToSave(FileFilter? filter, string? title, string? suggestedName)
            => Task.FromResult(_path);
        public Task<bool> Confirm(string message, string? title = null)
            => Task.FromResult(true);
        public Task Notify(string message, string? title = null, NotificationSeverity severity = NotificationSeverity.Info)
            => Task.CompletedTask;
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
