using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class StatusBarVMTests
{
    private static (StatusBarVM bar, NotesViewVM notes, NotebooksRootVM nbs, NoteFormVM form,
                    InMemoryNoteRepository repo) Build()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var notes = NotesViewVM.Builder()
            .Name("notes").Services(hub, dispatcher).Repository(repo).PageSize(5).Build();
        var nbs = NotebooksRootVM.Builder()
            .Name("nbs").Services(hub, dispatcher).Repository(repo).Build();
        var form = NoteFormVM.Builder()
            .Name("form").Services(hub, dispatcher).Repository(repo).Build();
        var bar = StatusBarVM.Builder()
            .Name("status").Services(hub, dispatcher)
            .NotesView(notes).Notebooks(nbs).NoteForm(form).Build();
        notes.Construct();
        nbs.Construct();
        form.Construct();
        bar.Construct();
        return (bar, notes, nbs, form, repo);
    }

    [Fact]
    public async Task NoteCountText_recomputes_when_NotesView_emits_PropertyChanged()
    {
        var (bar, notes, _, _, _) = Build();
        var initial = bar.NoteCountText.Value;
        await notes.BindToAsync("nb-reviews");
        Assert.NotEqual(initial, bar.NoteCountText.Value);
        Assert.Contains("notes", bar.NoteCountText.Value); // "7 notes"
    }

    [Fact]
    public async Task StarredText_reflects_starred_count_in_current_filter()
    {
        var (bar, notes, _, _, _) = Build();
        await notes.BindToAsync("nb-reviews");
        // 2 starred in nb-reviews per SeedData.
        Assert.Equal("2 starred", bar.StarredText.Value);
    }

    [Fact]
    public void EditingText_says_no_selection_until_form_is_bound()
    {
        var (bar, _, _, form, _) = Build();
        Assert.Equal("No selection", bar.EditingText.Value);
        form.BindTo(new NoteModel(
            "n1", "nb-reviews", "Title", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow));
        Assert.Contains("Editing:", bar.EditingText.Value);
        Assert.Contains("Title", bar.EditingText.Value);
    }

    [Fact]
    public void EditingText_dirty_marker_appears_on_mutation()
    {
        var (bar, _, _, form, _) = Build();
        form.BindTo(new NoteModel(
            "n1", "nb-reviews", "Title", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow));
        Assert.DoesNotContain(" *", bar.EditingText.Value);
        form.Draft = form.Draft with { Title = "Title v2" };
        Assert.Contains(" *", bar.EditingText.Value);
    }

    [Fact]
    public async Task Equality_guard_no_duplicate_DerivedProperty_emissions_for_same_value()
    {
        var (bar, notes, _, _, _) = Build();
        await notes.BindToAsync("nb-reviews");
        var emits = 0;
        using var sub = bar.NoteCountText.ValueChanged.Subscribe(_ => emits++);
        // Triggering RecomputeFiltered with the same predicate => same count => no emission.
        notes.Filter = null;
        notes.Filter = null;
        notes.ShowStarredOnly = false;
        Assert.Equal(0, emits);
    }

    // ── BindableDerived INPC adapter contract ─────────────────────────────

    [Fact]
    public async Task Bindable_sidecars_raise_PropertyChanged_for_Value_on_recompute()
    {
        var (bar, notes, _, _, _) = Build();
        var observedCount = new System.Collections.Generic.List<string?>();
        var observedStarred = new System.Collections.Generic.List<string?>();
        bar.NoteCountTextBindable.PropertyChanged += (_, e) => observedCount.Add(e.PropertyName);
        bar.StarredTextBindable.PropertyChanged += (_, e) => observedStarred.Add(e.PropertyName);

        await notes.BindToAsync("nb-reviews");

        Assert.NotEmpty(observedCount);
        Assert.All(observedCount, n => Assert.Equal("Value", n));
        Assert.NotEmpty(observedStarred);
        Assert.Equal(bar.NoteCountText.Value, bar.NoteCountTextBindable.Value);
        Assert.Equal(bar.StarredText.Value, bar.StarredTextBindable.Value);
    }

    [Fact]
    public void EditingTextBindable_PropertyChanged_fires_when_form_draft_mutates()
    {
        var (bar, _, _, form, _) = Build();
        var observed = new System.Collections.Generic.List<string?>();
        bar.EditingTextBindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        form.BindTo(new NoteModel(
            "n1", "nb-reviews", "Hello", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow));
        form.Title = "World";

        Assert.NotEmpty(observed);
        Assert.Equal(bar.EditingText.Value, bar.EditingTextBindable.Value);
    }
}
