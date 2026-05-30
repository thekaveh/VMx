using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
using VMx.Notifications;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NoteFormVMTests
{
    private static (NoteFormVM form, InMemoryNoteRepository repo) Build()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var form = NoteFormVM.Builder()
            .Name("form").Services(hub, dispatcher).Repository(repo).Build();
        form.Construct();
        return (form, repo);
    }

    private static NoteModel SampleNote(string title = "Hello") =>
        new("note-01", "nb-reviews", title, Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);

    [Fact]
    public void Implements_IReconstructable()
    {
        var (form, _) = Build();
        Assert.IsAssignableFrom<IReconstructable>(form);
    }

    [Fact]
    public void BindTo_snapshots_and_clears_IsDirty()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote());
        Assert.False(form.IsDirty);
        Assert.Equal("Hello", form.Snapshot.Title);
    }

    [Fact]
    public void Mutating_Draft_sets_IsDirty_true()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote());
        form.Draft = form.Draft with { Title = "Edited" };
        Assert.True(form.IsDirty);
        Assert.Equal("Edited", form.Draft.Title);
    }

    [Fact]
    public async Task Approve_persists_clears_dirty_and_resnapshots()
    {
        var (form, repo) = Build();
        var note = (await repo.LoadAllAsync()).Notes.First();
        form.BindTo(note);
        Assert.False(form.IsDirty);
        form.Draft = form.Draft with { Title = "Edited" };
        Assert.True(form.IsDirty);
        await form.ApproveAsync();
        Assert.False(form.IsDirty);
        Assert.Equal("Edited", form.Snapshot.Title);
        var reload = await repo.LoadNotesAsync(note.NotebookId);
        Assert.Equal("Edited", reload.Single(n => n.Id == note.Id).Title);
    }

    [Fact]
    public void Deny_reverts_draft_to_snapshot()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote("Original"));
        form.Draft = form.Draft with { Title = "Changed" };
        Assert.True(form.IsDirty);
        form.DenyCommand.Execute(null);
        Assert.False(form.IsDirty);
        Assert.Equal("Original", form.Draft.Title);
    }

    [Fact]
    public void ApproveCommand_CanExecute_requires_IsDirty_AND_IsValid()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote("Original"));
        // Not dirty: false.
        Assert.False(form.ApproveCommand.CanExecute(null));
        // Dirty + valid: true.
        form.Draft = form.Draft with { Title = "New title" };
        Assert.True(form.ApproveCommand.CanExecute(null));
        // Dirty but invalid (empty title): false.
        form.Draft = form.Draft with { Title = "" };
        Assert.False(form.IsValid);
        Assert.False(form.ApproveCommand.CanExecute(null));
    }

    [Fact]
    public void Empty_title_makes_IsValid_false()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote(""));
        Assert.False(form.IsValid);
    }

    [Fact]
    public void AddTagCommand_appends_unique_tag_and_clears_TagDraft()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote());
        form.TagDraft = "security";
        form.AddTagCommand.Execute(null);
        Assert.Contains("security", form.Draft.Tags);
        Assert.Equal(string.Empty, form.TagDraft);
        // Idempotent: re-adding the same tag is a no-op.
        form.TagDraft = "security";
        form.AddTagCommand.Execute(null);
        Assert.Single(form.Draft.Tags);
    }

    [Fact]
    public void RemoveTagCommand_removes_tag()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote() with { Tags = new[] { "a", "b" } });
        form.RemoveTagCommand.Execute("a");
        Assert.DoesNotContain("a", form.Draft.Tags);
        Assert.Contains("b", form.Draft.Tags);
    }

    // ── Phase 5.a binding gap #1: two-way scalar setters ──────────────────

    [Fact]
    public void Setting_Title_scalar_flips_IsDirty_true_and_enables_ApproveCommand()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote("Original"));
        Assert.False(form.IsDirty);
        Assert.False(form.ApproveCommand.CanExecute(null));

        form.Title = "Edited";

        Assert.Equal("Edited", form.Title);
        Assert.Equal("Edited", form.Draft.Title);
        Assert.True(form.IsDirty);
        Assert.True(form.ApproveCommand.CanExecute(null));
    }

    [Fact]
    public void Setting_Title_back_to_snapshot_value_flips_IsDirty_false()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote("Original"));
        form.Title = "Edited";
        Assert.True(form.IsDirty);

        form.Title = "Original";

        Assert.False(form.IsDirty);
        Assert.False(form.ApproveCommand.CanExecute(null));
    }

    [Fact]
    public void Setting_Body_and_Starred_scalars_round_trip_into_Draft()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote());
        form.Body = "New body content";
        form.Starred = true;
        Assert.Equal("New body content", form.Draft.Body);
        Assert.True(form.Draft.Starred);
        Assert.True(form.IsDirty);
    }

    [Fact]
    public void Setting_Title_to_same_value_is_no_op_no_dirty_flip()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote("Hello"));
        form.Title = "Hello";
        Assert.False(form.IsDirty);
    }

    [Fact]
    public void Scalar_setters_emit_PropertyChangedMessage_on_hub_for_Title_Body_Starred()
    {
        var (form, _) = Build();
        form.BindTo(SampleNote());
        var observed = new System.Collections.Generic.List<string>();
        using var sub = form.Hub.Messages
            .OfType<VMx.Messages.PropertyChangedMessage<VMx.Components.IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, form))
            .Subscribe(m => observed.Add(m.PropertyName));

        form.Title = "T2";
        form.Body = "B2";
        form.Starred = true;

        Assert.Contains(nameof(NoteFormVM.Title), observed);
        Assert.Contains(nameof(NoteFormVM.Body), observed);
        Assert.Contains(nameof(NoteFormVM.Starred), observed);
    }

    [Fact]
    public void Scalar_setters_are_no_ops_when_no_note_is_bound()
    {
        var (form, _) = Build();
        // Pre-bind: form has no inner FormVM yet — setters must safely no-op.
        form.Title = "ignored";
        form.Body = "ignored";
        form.Starred = true;
        Assert.False(form.IsDirty);
    }

    // ── Audit pass #1, B3: ApproveAsync publishes "Saved" notification ────

    [Fact]
    public async Task ApproveAsync_publishes_Saved_notification()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot) if (!observed.Contains(n)) observed.Add(n);
        });
        var form = NoteFormVM.Builder()
            .Name("form").Services(hub, dispatcher).Repository(repo)
            .NotificationHub(notificationHub).Build();
        form.Construct();
        var note = (await repo.LoadAllAsync()).Notes.First();
        form.BindTo(note);
        form.Title = "Edited title";

        await form.ApproveAsync();

        Assert.Contains(observed, n => n.Message.Contains("Saved") && n.Message.Contains("Edited title"));
    }
}
