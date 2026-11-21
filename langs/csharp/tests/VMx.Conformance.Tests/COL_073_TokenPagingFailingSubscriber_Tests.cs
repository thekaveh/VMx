using System.Collections.Specialized;
using FluentAssertions;
using VMx.Collections;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COL-073: a failing subscriber of a token-paging notification step skips no
/// later step of the committed load or refresh (spec/21-collections.md §6.2,
/// ADR-0239, extends ADR-0220). The first failure reaches the caller after the
/// last step.
/// </summary>
public class COL_073_TokenPagingFailingSubscriber_Tests
{
    private sealed class HandlerFailure() : Exception("handler failed");

    /// <summary>The first page can change between calls; a later page is terminal.</summary>
    private sealed class Backend
    {
        public TokenPage<int, string> FirstPage { get; set; } = new([1, 2], "t2");

        public Task<TokenPage<int, string>> Fetch(string? token) =>
            Task.FromResult(token is null ? FirstPage : new TokenPage<int, string>([3], null));
    }

    // Observes a command that is not executing: a command raises its own
    // CanExecuteChanged when it starts and finishes, which is not a re-signal.
    private static List<string> Trace(TokenPagedComposition<int, string> sut, AsyncRelayCommand observed)
    {
        var trace = new List<string>();
        sut.CollectionChanged += (_, e) => trace.Add($"collection:{e.Action}");
        sut.PropertyChanged += (_, e) => trace.Add($"property:{e.PropertyName}");
        observed.CanExecuteChanged += (_, _) => trace.Add("command:CanExecuteChanged");
        return trace;
    }

    [Fact, Trait("Conformance", "COL-073")]
    public async Task COL_073_LoadAppend_FailingResetHandler_SkipsNoLaterStep()
    {
        using var sut = new TokenPagedComposition<int, string>(
            _ => Task.FromResult(new TokenPage<int, string>([1, 2], null)));
        var later = 0;
        sut.CollectionChanged += (_, _) => throw new HandlerFailure();
        sut.CollectionChanged += (_, e) => { if (e.Action == NotifyCollectionChangedAction.Reset) later++; };
        var trace = Trace(sut, sut.RefreshCommand);

        var act = () => sut.LoadMoreCommand.ExecuteAsync();

        await act.Should().ThrowAsync<HandlerFailure>();
        later.Should().Be(1);
        trace.Should().Equal(
            "collection:Reset",
            "property:Items",
            "property:CurrentToken",
            "property:HasMore",
            "command:CanExecuteChanged");
        sut.Items.Should().Equal(1, 2);
        sut.HasMore.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COL-073")]
    public async Task COL_073_ReplacingRefresh_FailingResetHandler_SkipsNoLaterStep()
    {
        var backend = new Backend();
        using var sut = new TokenPagedComposition<int, string>(backend.Fetch);
        await sut.LoadMoreCommand.ExecuteAsync();
        backend.FirstPage = new([9], null);
        var later = 0;
        sut.CollectionChanged += (_, _) => throw new HandlerFailure();
        sut.CollectionChanged += (_, e) => { if (e.Action == NotifyCollectionChangedAction.Reset) later++; };
        var trace = Trace(sut, sut.LoadMoreCommand);

        var act = () => sut.RefreshCommand.ExecuteAsync();

        await act.Should().ThrowAsync<HandlerFailure>();
        later.Should().Be(1);
        trace.Should().Equal(
            "collection:Reset",
            "property:Items",
            "property:CurrentToken",
            "property:HasMore",
            "command:CanExecuteChanged");
        sut.Items.Should().Equal(9);
        sut.CurrentToken.Should().BeNull();
        sut.HasMore.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COL-073")]
    public async Task COL_073_FailingPropertyHandler_SkipsNoLaterPropertyOrCommandStep()
    {
        using var sut = new TokenPagedComposition<int, string>(
            _ => Task.FromResult(new TokenPage<int, string>([1, 2], null)));
        sut.PropertyChanged += (_, _) => throw new HandlerFailure();
        var trace = Trace(sut, sut.RefreshCommand);

        var act = () => sut.LoadMoreCommand.ExecuteAsync();

        await act.Should().ThrowAsync<HandlerFailure>();
        trace.Should().Equal(
            "collection:Reset",
            "property:Items",
            "property:CurrentToken",
            "property:HasMore",
            "command:CanExecuteChanged");
    }

    [Fact, Trait("Conformance", "COL-073")]
    public async Task COL_073_DisposingResetHandler_StopsTheLaterPropertyAndCommandSteps()
    {
        using var sut = new TokenPagedComposition<int, string>(
            _ => Task.FromResult(new TokenPage<int, string>([1, 2], null)));
        sut.CollectionChanged += (_, _) => sut.Dispose();
        var trace = Trace(sut, sut.RefreshCommand);

        await sut.LoadMoreCommand.ExecuteAsync();

        trace.Should().Equal("collection:Reset");
    }
}
