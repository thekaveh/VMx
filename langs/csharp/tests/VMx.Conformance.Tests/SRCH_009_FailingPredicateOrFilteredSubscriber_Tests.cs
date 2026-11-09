using System.Reactive.Concurrency;
using FluentAssertions;
using VMx.Capabilities;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// SRCH-009: a failing predicate or <c>Filtered</c> subscriber keeps the
/// helper live. A failing predicate keeps the last snapshot, and C# discards
/// both failures (spec/06 §8.2, spec/03 §3.6, ADR-0191).
/// </summary>
public class SRCH_009_FailingPredicateOrFilteredSubscriber_Tests
{
    private sealed class PredicateFailure() : Exception("predicate failed");

    private sealed class SubscriberFailure() : Exception("subscriber failed");

    private static bool Matches(string item, string term)
    {
        if (term == "boom") throw new PredicateFailure();
        return item.Contains(term, StringComparison.Ordinal);
    }

    [Fact, Trait("Conformance", "SRCH-009")]
    public void SRCH_009_Failing_Predicate_And_Subscriber_Keep_Filtered_Live()
    {
        using var state = new SearchableState<string>(
            () => ["apple", "banana"], Matches, TimeSpan.Zero, ImmediateScheduler.Instance);
        var a = new List<IReadOnlyList<string>>();
        var b = new List<IReadOnlyList<string>>();
        state.Filtered.Subscribe(snapshot =>
        {
            a.Add(snapshot);
            throw new SubscriberFailure();
        });
        state.Filtered.Subscribe(b.Add);
        a.Clear();
        b.Clear();

        state.Invoking(s => s.SearchTerm = "boom").Should().NotThrow();
        a.Should().BeEmpty();
        b.Should().BeEmpty();

        state.Invoking(s => s.SearchTerm = "an").Should().NotThrow();
        a.Should().ContainSingle().Which.Should().Equal("banana");
        b.Should().ContainSingle().Which.Should().Equal("banana");

        state.Invoking(s => s.Search()).Should().NotThrow();
        a.Should().HaveCount(2);
        a[1].Should().Equal("banana");
        b.Should().HaveCount(2);
        b[1].Should().Equal("banana");
    }

    [Fact, Trait("Conformance", "SRCH-009")]
    public void SRCH_009_Failing_Predicate_On_Search_Keeps_Last_Snapshot()
    {
        var term = "";
        using var state = new SearchableState<string>(
            () => ["apple", "banana"],
            (item, t) => term == "boom" ? throw new PredicateFailure() : Matches(item, t),
            TimeSpan.Zero,
            ImmediateScheduler.Instance);
        var b = new List<IReadOnlyList<string>>();
        state.SearchTerm = "an";
        state.Filtered.Subscribe(b.Add);

        term = "boom";
        state.Invoking(s => s.Search()).Should().NotThrow();
        term = "";
        state.Search();

        b.Should().HaveCount(2);
        b[0].Should().Equal("banana");
        b[1].Should().Equal("banana");
    }
}
