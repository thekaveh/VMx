using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
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
}
