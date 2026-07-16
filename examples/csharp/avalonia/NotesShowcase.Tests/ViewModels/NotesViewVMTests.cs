using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NotesViewVMTests
{
    private static NotesViewVM BuildVM(
        InMemoryNoteRepository repo,
        IScheduler? searchScheduler = null,
        TimeSpan? debounce = null)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        return NotesViewVM.Builder()
            .Name("notes")
            .Services(hub, dispatcher)
            .Repository(repo)
            .PageSize(5)
            .SearchDebounce(debounce ?? TimeSpan.FromMilliseconds(150))
            .SearchScheduler(searchScheduler ?? ImmediateScheduler.Instance)
            .Build();
    }

    private static async Task<(NotesViewVM vm, InMemoryNoteRepository repo)> BuildAndBindAsync(
        string notebookId = "nb-reviews",
        IScheduler? searchScheduler = null,
        TimeSpan? debounce = null)
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero);
        var vm = BuildVM(repo, searchScheduler, debounce);
        vm.Construct();
        await vm.BindToAsync(notebookId);
        return (vm, repo);
    }

    [Fact]
    public async Task BindToAsync_loads_notes_for_the_notebook()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        Assert.NotEmpty(vm.VisibleItems);
        Assert.All(vm.FilteredItems, n => Assert.Equal("nb-reviews", n.Model.NotebookId));
        Assert.Equal("nb-reviews", vm.BoundNotebookId);
    }

    [Fact]
    public async Task PageSize_5_yields_two_pages_for_seven_reviews_notes()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        // 7 review notes / page-size 5 => 2 pages
        Assert.Equal(2, vm.PageCount);
        Assert.Equal(5, vm.VisibleItems.Count);
        vm.MoveToNextPageCommand.Execute(null);
        Assert.Equal(2, vm.VisibleItems.Count);
    }

    [Fact]
    public async Task Pagination_no_op_at_boundaries()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        var first = vm.CurrentPageIndex;
        Assert.False(vm.MoveToFirstPageCommand.CanExecute(null));
        Assert.False(vm.MoveToPreviousPageCommand.CanExecute(null));
        Assert.True(vm.MoveToNextPageCommand.CanExecute(null));
        Assert.True(vm.MoveToLastPageCommand.CanExecute(null));
        vm.MoveToFirstPageCommand.Execute(null);
        Assert.Equal(first, vm.CurrentPageIndex);
        vm.MoveToLastPageCommand.Execute(null);
        var last = vm.CurrentPageIndex;
        Assert.True(vm.MoveToFirstPageCommand.CanExecute(null));
        Assert.True(vm.MoveToPreviousPageCommand.CanExecute(null));
        Assert.False(vm.MoveToNextPageCommand.CanExecute(null));
        Assert.False(vm.MoveToLastPageCommand.CanExecute(null));
        vm.MoveToNextPageCommand.Execute(null);
        Assert.Equal(last, vm.CurrentPageIndex);
    }

    [Fact]
    public async Task ShowStarredOnly_filter_restricts_to_starred_notes()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        vm.ShowStarredOnly = true;
        Assert.All(vm.FilteredItems, n => Assert.True(n.Starred));
        Assert.NotEmpty(vm.FilteredItems); // nb-reviews has 2 starred per seed
    }

    [Fact]
    public async Task ShowStarredOnly_false_restores_all_notes()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        vm.ShowStarredOnly = true;
        var starredCount = vm.FilteredItems.Count;
        vm.ShowStarredOnly = false;
        Assert.True(vm.FilteredItems.Count > starredCount);
    }

    [Fact]
    public async Task Filter_predicate_restricts_visible_items()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        vm.Filter = n => n.Title.Contains("Q1");
        Assert.Single(vm.FilteredItems);
        Assert.Contains("Q1", vm.FilteredItems[0].Title);
        vm.Filter = null;
        Assert.True(vm.FilteredItems.Count > 1);
    }

    [Fact]
    public async Task BindToAsync_to_different_notebook_swaps_items()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        var beforeIds = vm.FilteredItems.Select(i => i.NoteId).ToList();
        await vm.BindToAsync("nb-work");
        var afterIds = vm.FilteredItems.Select(i => i.NoteId).ToList();
        Assert.NotEqual(beforeIds, afterIds);
        Assert.All(vm.FilteredItems, n => Assert.Equal("nb-work", n.Model.NotebookId));
    }

    [Fact]
    public async Task IsEmpty_true_when_filter_excludes_everything()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        Assert.False(vm.IsEmptyDerived.Value);
        vm.Filter = _ => false;
        Assert.True(vm.IsEmpty);
        Assert.True(vm.IsEmptyDerived.Value);
        Assert.Empty(vm.VisibleItems);
    }

    [Fact]
    public async Task PageLabel_reflects_current_page_and_count()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        Assert.Equal("Page 1 of 2", vm.PageLabel);
        Assert.Equal("Page 1 of 2", vm.PageLabelDerived.Value);
        vm.MoveToNextPageCommand.Execute(null);
        Assert.Equal("Page 2 of 2", vm.PageLabel);
        Assert.Equal("Page 2 of 2", vm.PageLabelDerived.Value);
    }

    [Fact]
    public async Task Search_debounced_via_TestScheduler_only_emits_after_window()
    {
        var ts = new TestScheduler();
        var (vm, _) = await BuildAndBindAsync(
            "nb-reviews",
            searchScheduler: ts,
            debounce: TimeSpan.FromMilliseconds(150));
        // Initial: 7 visible (across 2 pages — 5 on page 1).
        var before = vm.FilteredItems.Count;
        Assert.True(before > 1);

        vm.SearchTerm = "Q1";
        // Before the debounce window elapses, the recompute hasn't fired yet,
        // so FilteredItems still reflects the prior term ("").
        ts.AdvanceBy(TimeSpan.FromMilliseconds(50).Ticks);
        Assert.Equal(before, vm.FilteredItems.Count);
        // Advance past the 150 ms debounce window.
        ts.AdvanceBy(TimeSpan.FromMilliseconds(150).Ticks);
        Assert.Single(vm.FilteredItems);
        Assert.Contains("Q1", vm.FilteredItems[0].Title);
    }

    [Fact]
    public async Task Current_setter_emits_PropertyChanged_and_is_idempotent()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        var first = vm.VisibleItems[0];
        vm.Current = first;
        Assert.Same(first, vm.Current);
        vm.Current = first; // idempotent
        Assert.Same(first, vm.Current);
        vm.Current = null;
        Assert.Null(vm.Current);
    }

    [Fact]
    public async Task Reconstruct_resets_lifecycle_and_keeps_items_via_rebind()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        var before = vm.FilteredItems.Count;
        vm.Reconstruct();
        // After reconstruct the prior items were torn down — a rebind restores them.
        await vm.BindToAsync("nb-reviews");
        Assert.Equal(before, vm.FilteredItems.Count);
    }

    // ── end-to-end delete-path coverage: end-to-end delete pathway coverage ────────
    // The full pathway (repo.DeleteNoteAsync → remove from _inner → clear
    // Current → dispose) had 0 % coverage. Drive it through NoteVM's
    // DeleteCommand (the only public entry-point to NotesViewVM.DeleteNote).

    [Fact]
    public async Task DeleteNoteAsync_removes_from_inner_and_clears_current_and_persists()
    {
        var seed = SeedData.Build();
        var repo = new InMemoryNoteRepository(
            seed,
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            deleteNoteDelay: TimeSpan.Zero);
        var hub = new VMx.Services.MessageHub();
        var dispatcher = new VMx.Services.RxDispatcher(
            System.Reactive.Concurrency.ImmediateScheduler.Instance,
            System.Reactive.Concurrency.ImmediateScheduler.Instance);
        var vm = NotesViewVM.Builder()
            .Name("notes").Services(hub, dispatcher).Repository(repo).PageSize(5)
            .Build();
        vm.Construct();
        await vm.BindToAsync("nb-personal");
        var before = vm.Inner.Count;
        var target = vm.Inner[0];
        vm.Current = target;

        // Drive delete through NoteVM.DeleteCommand (raw, no confirm wrapped
        // for this test build) — this is the path NotesListView.axaml fires
        // when the user clicks the delete button next to a note.
        target.DeleteCommand.Execute(null);
        // Repo delete is awaited inside DeleteNoteAsyncInternal; wait for the
        // continuation to remove the row.
        await TestWait.WaitUntilAsync(() => vm.Inner.Count == before - 1);

        Assert.Equal(before - 1, vm.Inner.Count);
        Assert.Null(vm.Current);
        // Persistence check: the repo no longer returns the deleted note.
        var reload = await repo.LoadNotesAsync("nb-personal");
        Assert.DoesNotContain(reload, n => n.Id == target.NoteId);
    }

    [Fact]
    public async Task Repository_search_notes_returns_token_pages_over_all_notes()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero);

        var first = await repo.SearchNotesAsync("review", token: null, pageSize: 2);

        Assert.Equal(2, first.Items.Count);
        Assert.Equal("2", first.NextToken);
        Assert.All(first.Items, n =>
            Assert.Contains("review", $"{n.Title} {n.Body} {string.Join(" ", n.Tags)}".ToLowerInvariant()));

        var second = await repo.SearchNotesAsync("review", first.NextToken, pageSize: 2);

        Assert.NotEmpty(second.Items);
        Assert.NotEqual(first.Items[0].Id, second.Items[0].Id);
    }

    [Fact]
    public async Task Repository_search_notes_rejects_malformed_and_extreme_offsets()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero);
        var first = await repo.SearchNotesAsync("review", token: null, pageSize: 2);

        var malformed = await repo.SearchNotesAsync("review", token: "2junk", pageSize: 2);
        var extreme = await repo.SearchNotesAsync(
            "review", token: int.MaxValue.ToString(), pageSize: int.MaxValue);

        Assert.Equal(first.Items, malformed.Items);
        Assert.Empty(extreme.Items);
        Assert.Null(extreme.NextToken);
    }

    [Fact]
    public async Task Direct_dispose_releases_live_note_children_and_binding_state()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.BindToAsync("nb-personal");
        var children = vm.Inner.ToArray();

        vm.Dispose();

        Assert.NotEmpty(children);
        Assert.All(children, child => Assert.Equal(ConstructionStatus.Disposed, child.Status));
        Assert.Empty(vm.Inner);
        Assert.Null(vm.BoundNotebookId);
    }

    [Fact]
    public async Task GlobalSearchVM_refreshes_resets_terms_and_loads_more()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero);
        var vm = GlobalSearchVM.Builder()
            .Name("global-search")
            .Services(hub, dispatcher)
            .Repository(repo)
            .PageSize(2)
            .SearchDebounce(TimeSpan.Zero)
            .Build();

        vm.SearchTerm = "review";
        await vm.RefreshCommand.ExecuteAsync();
        Assert.Equal(2, vm.Results.Count);
        Assert.True(vm.HasMore);

        await vm.LoadMoreCommand.ExecuteAsync();
        Assert.True(vm.Results.Count > 2);
        var replacedResults = vm.Results.ToArray();

        vm.SearchTerm = "travel";
        await vm.RefreshCommand.ExecuteAsync();
        Assert.All(vm.Results, n => Assert.Equal("nb-personal", n.Model.NotebookId));
        var finalResults = vm.Results.ToArray();
        vm.Dispose();
        Assert.All(replacedResults.Concat(finalResults), result =>
            Assert.Equal(ConstructionStatus.Disposed, result.Status));
    }
}
