using FluentAssertions;
using VMx.Collections;
using VMx.Components;
using VMx.Composites;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-024..COL-031 — token pagination and composite source paging.
/// </summary>
public class COL_024_to_031_TokenPagedCompositionTests
{
    [Fact, Trait("Conformance", "COL-024")]
    public void COL_024_TokenPagedInitialState()
    {
        var sut = new TokenPagedComposition<int, string>(_ =>
            Task.FromResult(new TokenPage<int, string>([1, 2], "next")));

        sut.Items.Should().BeEmpty();
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeTrue();
        sut.LoadMoreCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact, Trait("Conformance", "COL-025")]
    public async Task COL_025_LoadMoreAppendsItemsAndAdvancesToken()
    {
        var calls = new List<string?>();
        var sut = new TokenPagedComposition<int, string>(token =>
        {
            calls.Add(token);
            return Task.FromResult(token is null
                ? new TokenPage<int, string>([1, 2], "two")
                : new TokenPage<int, string>([3], null));
        });

        await sut.LoadMoreCommand.ExecuteAsync();
        sut.Items.Should().Equal(1, 2);
        sut.CurrentToken.Should().Be("two");
        sut.HasMore.Should().BeTrue();

        await sut.LoadMoreCommand.ExecuteAsync();
        sut.Items.Should().Equal(1, 2, 3);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
        calls.Should().Equal(null, "two");
    }

    [Fact]
    public async Task LoadMore_Does_Not_Mutate_Or_Notify_When_Disposed_During_Fetch()
    {
        var page = new TaskCompletionSource<TokenPage<int, string>>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        using var sut = new TokenPagedComposition<int, string>(_ => page.Task);
        var collectionEvents = 0;
        var propertyEvents = 0;
        sut.CollectionChanged += (_, _) => collectionEvents++;
        sut.PropertyChanged += (_, _) => propertyEvents++;

        var load = sut.LoadMoreCommand.ExecuteAsync();
        sut.Dispose();
        page.SetResult(new TokenPage<int, string>([1, 2], "next"));
        await load;

        sut.Items.Should().BeEmpty();
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeTrue();
        collectionEvents.Should().Be(0);
        propertyEvents.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COL-026")]
    public async Task COL_026_TerminalTokenDisablesLoadMore()
    {
        var sut = new TokenPagedComposition<int, string>(_ =>
            Task.FromResult(new TokenPage<int, string>([1], null)));

        await sut.LoadMoreCommand.ExecuteAsync();

        sut.HasMore.Should().BeFalse();
        sut.LoadMoreCommand.CanExecute(null).Should().BeFalse();
    }

    // A change driven by one command must re-raise the OTHER command's
    // CanExecuteChanged (parity with Python/TS/Swift, which share a command-changed
    // trigger): a Refresh that flips HasMore back to true re-enables LoadMore.
    [Fact]
    public async Task Refresh_ReSignals_LoadMore_CanExecuteChanged()
    {
        var pages = new Queue<TokenPage<int, string>>([
            new([1], null),    // first LoadMore → terminal token, HasMore = false
            new([2], "more"),  // Refresh refetch → non-null token, HasMore = true
        ]);
        var sut = new TokenPagedComposition<int, string>(_ => Task.FromResult(pages.Dequeue()));

        await sut.LoadMoreCommand.ExecuteAsync();
        sut.LoadMoreCommand.CanExecute(null).Should().BeFalse("terminal token disabled LoadMore");

        var loadMoreRequeries = 0;
        sut.LoadMoreCommand.CanExecuteChanged += (_, _) => loadMoreRequeries++;

        await sut.RefreshCommand.ExecuteAsync();

        sut.HasMore.Should().BeTrue("refresh refetched a page with a non-null token");
        loadMoreRequeries.Should().BeGreaterThan(0,
            "a Refresh re-enabling LoadMore must re-raise LoadMore's CanExecuteChanged");
        sut.LoadMoreCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact, Trait("Conformance", "COL-027")]
    public async Task COL_027_RefreshClearsAndRefetchesFirstPage()
    {
        var pages = new Queue<TokenPage<int, string>>([
            new([1, 2], "next"),
            new([9], null),
        ]);
        var sut = new TokenPagedComposition<int, string>(token =>
        {
            token.Should().BeNull();
            return Task.FromResult(pages.Dequeue());
        });

        await sut.LoadMoreCommand.ExecuteAsync();
        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(9);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
    }

    [Fact]
    public async Task Refresh_Supersedes_An_Older_InFlight_LoadMore()
    {
        var pages = new[]
        {
            new TaskCompletionSource<TokenPage<int, string>>(
                TaskCreationOptions.RunContinuationsAsynchronously),
            new TaskCompletionSource<TokenPage<int, string>>(
                TaskCreationOptions.RunContinuationsAsynchronously),
        };
        var call = -1;
        var sut = new TokenPagedComposition<int, string>(
            _ => pages[Interlocked.Increment(ref call)].Task);

        var load = sut.LoadMoreCommand.ExecuteAsync();
        var refresh = sut.RefreshCommand.ExecuteAsync();
        pages[1].SetResult(new TokenPage<int, string>([9], "fresh"));
        await refresh;
        sut.Items.Should().Equal(9);

        pages[0].SetResult(new TokenPage<int, string>([1], "stale"));
        await load;

        sut.Items.Should().Equal(9);
        sut.CurrentToken.Should().Be("fresh");
    }

    [Fact]
    public async Task Refresh_Does_Not_Mutate_Or_Notify_When_Disposed_During_Fetch()
    {
        var page = new TaskCompletionSource<TokenPage<int, string>>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        using var sut = new TokenPagedComposition<int, string>(_ => page.Task);
        var collectionEvents = 0;
        var propertyEvents = 0;
        sut.CollectionChanged += (_, _) => collectionEvents++;
        sut.PropertyChanged += (_, _) => propertyEvents++;

        var refresh = sut.RefreshCommand.ExecuteAsync();
        sut.Dispose();
        page.SetResult(new TokenPage<int, string>([9], null));
        await refresh;

        sut.Items.Should().BeEmpty();
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeTrue();
        collectionEvents.Should().Be(0);
        propertyEvents.Should().Be(0);
    }

    [Fact, Trait("Conformance", "COL-028")]
    public async Task COL_028_RefreshDedupGuardSuppressesRedundantMutation()
    {
        var sut = new TokenPagedComposition<int, string>(_ =>
            Task.FromResult(new TokenPage<int, string>([1, 2], "next")));
        var events = 0;
        sut.CollectionChanged += (_, _) => events++;

        await sut.LoadMoreCommand.ExecuteAsync();
        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2);
        events.Should().Be(1);
    }

    [Fact, Trait("Conformance", "COL-029")]
    public async Task COL_029_CollectionChangedUsesReset()
    {
        var sut = new TokenPagedComposition<int, string>(_ =>
            Task.FromResult(new TokenPage<int, string>([1, 2], null)));
        var actions = new List<System.Collections.Specialized.NotifyCollectionChangedAction>();
        sut.CollectionChanged += (_, e) => actions.Add(e.Action);

        await sut.LoadMoreCommand.ExecuteAsync();

        actions.Should().Equal(System.Collections.Specialized.NotifyCollectionChangedAction.Reset);
    }

    [Fact, Trait("Conformance", "COL-030")]
    public async Task COL_030_AutoConstructsAddedComponentVMs()
    {
        var child = ComponentVM.Builder().Name("child").WithNullServices().Build();
        var sut = new TokenPagedComposition<ComponentVM, string>(
            _ => Task.FromResult(new TokenPage<ComponentVM, string>([child], null)),
            autoConstructOnAdd: true);

        await sut.LoadMoreCommand.ExecuteAsync();

        child.IsConstructed.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "COL-031")]
    public void COL_031_PagedCompositionObservesCompositeCollectionChanges()
    {
        var composite = CompositeVM<ComponentVM>.Builder()
            .Name("source")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => [])
            .Build();
        using var sut = new PagedComposition<ComponentVM>(composite, pageSize: 2);
        var seen = new List<string?>();
        sut.PropertyChanged += (_, e) => seen.Add(e.PropertyName);

        composite.Add(ComponentVM.Builder().Name("a").WithNullServices().Build());

        sut.PageCount.Should().Be(1);
        seen.Should().Contain(nameof(PagedComposition<ComponentVM>.Items));
    }
}
