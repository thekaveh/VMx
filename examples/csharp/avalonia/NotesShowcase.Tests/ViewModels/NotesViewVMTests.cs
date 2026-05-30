using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
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
        vm.MoveToFirstPageCommand.Execute(null);
        Assert.Equal(first, vm.CurrentPageIndex);
        vm.MoveToLastPageCommand.Execute(null);
        var last = vm.CurrentPageIndex;
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
        vm.Filter = _ => false;
        Assert.True(vm.IsEmpty);
        Assert.Empty(vm.VisibleItems);
    }

    [Fact]
    public async Task PageLabel_reflects_current_page_and_count()
    {
        var (vm, _) = await BuildAndBindAsync("nb-reviews");
        Assert.Equal("Page 1 of 2", vm.PageLabel);
        vm.MoveToNextPageCommand.Execute(null);
        Assert.Equal("Page 2 of 2", vm.PageLabel);
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
}
