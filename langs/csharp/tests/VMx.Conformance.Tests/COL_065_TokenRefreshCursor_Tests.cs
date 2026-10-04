using FluentAssertions;
using VMx.Collections;
using VMx.Components;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-065 — a token-paged refresh keeps <c>Items</c> and
/// <c>CurrentToken</c> describing one loaded prefix (spec 21 §6.2, ADR-0136).
/// </summary>
public class COL_065_TokenRefreshCursorTests
{
    private static readonly Dictionary<string, TokenPage<int, string>> LaterPages = new()
    {
        ["t2"] = new([3, 4], "t3"),
        ["t3"] = new([5, 6], "t4"),
        ["t4"] = new([7], null),
    };

    /// <summary>First page can change between calls; later pages are keyed by token.</summary>
    private sealed class Backend
    {
        public List<string?> Requested { get; } = [];
        public TokenPage<int, string> FirstPage { get; set; } = new([1, 2], "t2");
        public Exception? Error { get; set; }

        public Task<TokenPage<int, string>> Fetch(string? token)
        {
            Requested.Add(token);
            if (Error is not null) return Task.FromException<TokenPage<int, string>>(Error);
            return Task.FromResult(token is null ? FirstPage : LaterPages[token]);
        }
    }

    private static async Task LoadAsync(TokenPagedComposition<int, string> sut, int count)
    {
        for (var i = 0; i < count; i++) await sut.LoadMoreCommand.ExecuteAsync();
    }

    private static List<string> Trace(TokenPagedComposition<int, string> sut)
    {
        var trace = new List<string>();
        sut.CollectionChanged += (_, e) => trace.Add($"collection:{e.Action}");
        sut.PropertyChanged += (_, e) => trace.Add($"property:{e.PropertyName}");
        sut.LoadMoreCommand.CanExecuteChanged += (_, _) => trace.Add("LoadMore:CanExecuteChanged");
        return trace;
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task COL_065_UnchangedHeadRefreshKeepsCursorSoLoadMoreNeverRefetchesPageTwo()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 3);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2, 3, 4, 5, 6);
        sut.CurrentToken.Should().Be("t4");
        sut.HasMore.Should().BeTrue();

        await sut.LoadMoreCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2, 3, 4, 5, 6, 7);
        api.Requested.Should().Equal(null, "t2", "t3", null, "t4");
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task ShorterMatchingNonTerminalHead_KeepsAccumulatorAndCursor()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.FirstPage = new([1], "u1");

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2, 3, 4);
        sut.CurrentToken.Should().Be("t3");
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task UnchangedSinglePage_AdoptsChangedOpaqueToken_WithoutReset()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 1);
        api.FirstPage = new([1, 2], "fresh-t2");
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2);
        sut.CurrentToken.Should().Be("fresh-t2");
        trace.Should().NotContain("collection:Reset");
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task UnchangedSinglePage_AdoptsNewlyTerminalToken()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 1);
        api.FirstPage = new([1, 2], null);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
        sut.LoadMoreCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task ChangedHead_ReplacesAccumulatorAndAdoptsRefreshedToken()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.FirstPage = new([9, 2], "u2");
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(9, 2);
        sut.CurrentToken.Should().Be("u2");
        trace.Count(entry => entry == "collection:Reset").Should().Be(1);
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task TerminalFirstPageShorterThanAccumulator_ReplacesIt()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.FirstPage = new([1, 2], null);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task EmptyTerminalFirstPage_ClearsNonEmptyAccumulator()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.FirstPage = new([], null);
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().BeEmpty();
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
        trace.Should().Contain("collection:Reset");
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task EmptyFirstPageWithContinuation_ReplacesAndAdoptsToken()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.FirstPage = new([], "u1");

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().BeEmpty();
        sut.CurrentToken.Should().Be("u1");
        sut.HasMore.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task RefreshAfterReachingTheEnd_KeepsTerminalCursor()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 4);
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(1, 2, 3, 4, 5, 6, 7);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
        sut.LoadMoreCommand.CanExecute(null).Should().BeFalse();
        trace.Should().NotContain("collection:Reset");
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task NoMutationBranch_PublishesPropertiesThenCommandSignal()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 3);
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        trace.Should().Equal(
            "property:Items",
            "property:CurrentToken",
            "property:HasMore",
            "LoadMore:CanExecuteChanged");
    }

    [Fact, Trait("Conformance", "COL-065")]
    public async Task ReplacementBranch_PublishesResetPropertiesThenCommandSignal()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 3);
        api.FirstPage = new([8, 9], "u2");
        var trace = Trace(sut);

        await sut.RefreshCommand.ExecuteAsync();

        trace.Should().Equal(
            "collection:Reset",
            "property:Items",
            "property:CurrentToken",
            "property:HasMore",
            "LoadMore:CanExecuteChanged");
    }

    [Fact]
    public async Task LoadStartedDuringRefresh_MakesTheRefreshResultStale()
    {
        var pages = Enumerable.Range(0, 3)
            .Select(_ => new TaskCompletionSource<TokenPage<int, string>>(
                TaskCreationOptions.RunContinuationsAsynchronously))
            .ToArray();
        var requested = new List<string?>();
        var call = -1;
        using var sut = new TokenPagedComposition<int, string>(token =>
        {
            lock (requested) requested.Add(token);
            return pages[Interlocked.Increment(ref call)].Task;
        });
        var first = sut.LoadMoreCommand.ExecuteAsync();
        pages[0].SetResult(new([1, 2], "t2"));
        await first;

        var refresh = sut.RefreshCommand.ExecuteAsync();
        var load = sut.LoadMoreCommand.ExecuteAsync();
        pages[1].SetResult(new([9], "stale"));
        await refresh;
        pages[2].SetResult(new([3, 4], "t3"));
        await load;

        requested.Should().Equal(null, null, "t2");
        sut.Items.Should().Equal(1, 2, 3, 4);
        sut.CurrentToken.Should().Be("t3");
    }

    [Fact]
    public async Task FailedRefreshFetch_LeavesItemsCursorAndNotificationsUntouched()
    {
        var api = new Backend();
        using var sut = new TokenPagedComposition<int, string>(api.Fetch);
        await LoadAsync(sut, 2);
        api.Error = new InvalidOperationException("offline");
        var trace = Trace(sut);

        var act = () => sut.RefreshCommand.ExecuteAsync();

        await act.Should().ThrowAsync<InvalidOperationException>().WithMessage("offline");
        sut.Items.Should().Equal(1, 2, 3, 4);
        sut.CurrentToken.Should().Be("t3");
        trace.Should().BeEmpty();
        sut.RefreshCommand.IsExecuting.Should().BeFalse();
    }

    [Fact]
    public async Task ThrowingPageComparer_LeavesItemsCursorAndNotificationsUntouched()
    {
        var api = new Backend();
        var fail = false;
        using var sut = new TokenPagedComposition<int, string>(
            api.Fetch,
            pagesEqual: (left, right) => fail
                ? throw new InvalidOperationException("comparer failed")
                : left.SequenceEqual(right));
        await LoadAsync(sut, 2);
        fail = true;
        var trace = Trace(sut);

        var act = () => sut.RefreshCommand.ExecuteAsync();

        await act.Should().ThrowAsync<InvalidOperationException>().WithMessage("comparer failed");
        sut.Items.Should().Equal(1, 2, 3, 4);
        sut.CurrentToken.Should().Be("t3");
        trace.Should().BeEmpty();
    }

    [Fact]
    public async Task DisposalBeforeRetainedPrefixRefreshCompletes_LeavesStateUntouched()
    {
        var api = new Backend();
        var held = new TaskCompletionSource<TokenPage<int, string>>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var hold = false;
        var sut = new TokenPagedComposition<int, string>(token => hold ? held.Task : api.Fetch(token));
        await LoadAsync(sut, 2);
        hold = true;
        var trace = Trace(sut);

        var refresh = sut.RefreshCommand.ExecuteAsync();
        sut.Dispose();
        held.SetResult(new([1, 2], "t2"));
        await refresh;

        sut.Items.Should().Equal(1, 2, 3, 4);
        sut.CurrentToken.Should().Be("t3");
        trace.Should().BeEmpty();
    }

    [Fact]
    public async Task RetainedAndReplacedItemVMs_AreNeverDisposedByTheComposition()
    {
        static ComponentVM Vm(string name) => ComponentVM.Builder().Name(name).WithNullServices().Build();
        ComponentVM[] loaded = [Vm("a"), Vm("b"), Vm("c"), Vm("d")];
        ComponentVM[] equalHead = [Vm("a"), Vm("b")];
        ComponentVM[] changedHead = [Vm("x"), Vm("y")];
        var refreshPage = equalHead;
        var firstLoad = true;
        using var sut = new TokenPagedComposition<ComponentVM, string>(
            token =>
            {
                if (token is not null)
                    return Task.FromResult(new TokenPage<ComponentVM, string>(loaded[2..], "t3"));
                if (!firstLoad) return Task.FromResult(new TokenPage<ComponentVM, string>(refreshPage, "t2"));
                firstLoad = false;
                return Task.FromResult(new TokenPage<ComponentVM, string>(loaded[..2], "t2"));
            },
            autoConstructOnAdd: true,
            pagesEqual: (left, right) => left.Select(vm => vm.Name).SequenceEqual(right.Select(vm => vm.Name)));
        await sut.LoadMoreCommand.ExecuteAsync();
        await sut.LoadMoreCommand.ExecuteAsync();

        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(loaded);
        sut.CurrentToken.Should().Be("t3");
        equalHead.Select(vm => vm.Status).Should().Equal(ConstructionStatus.Destructed, ConstructionStatus.Destructed);

        refreshPage = changedHead;
        await sut.RefreshCommand.ExecuteAsync();

        sut.Items.Should().Equal(changedHead);
        changedHead.Should().OnlyContain(vm => vm.IsConstructed);
        loaded.Should().OnlyContain(vm => vm.Status == ConstructionStatus.Constructed);
    }
}
