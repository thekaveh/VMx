using Microsoft.Reactive.Testing;
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Capabilities;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for search/filter, COMP-014..018 and GRP-007..010.
/// See spec/06-composite-vm.md §Search/filter, spec/07-group-vm.md, ADR-0014.
/// </summary>
public class SearchFilterConformanceTests
{
    private sealed class OwnedSearchItem : IDisposable
    {
        public OwnedSearchItem(string value) => Value = value;

        public string Value { get; }

        public int DisposeCount { get; private set; }

        public void Dispose() => DisposeCount++;
    }

    private static bool CISubstr(string item, string term) =>
        term.Length == 0 || item.ToLowerInvariant().Contains(term.ToLowerInvariant(), StringComparison.Ordinal);

    [Fact, Trait("Conformance", "COMP-014")]
    public void COMP_014_Defaults()
    {
        var items = new[] { "apple", "banana", "cherry" };
        using var s = new SearchableState<string>(
            () => items, CISubstr, debounce: TimeSpan.Zero);
        s.SearchTerm.Should().Be("");
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        snap.Last().Should().Equal(items);
    }

    [Fact, Trait("Conformance", "COMP-015")]
    public void COMP_015_SearchTerm_Triggers_Recompute()
    {
        var items = new[] { "apple", "banana", "cherry" };
        using var s = new SearchableState<string>(
            () => items, CISubstr, debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "an";
        snap.Last().Should().Equal("banana");
    }

    [Fact, Trait("Conformance", "COMP-016")]
    public void COMP_016_Search_Forces_Immediate()
    {
        var items = new[] { "one", "two" };
        using var s = new SearchableState<string>(
            () => items,
            (i, t) => t == "" || i == t,
            debounce: TimeSpan.FromSeconds(1));
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "two";
        s.Search();
        snap.Last().Should().Equal("two");
    }

    [Fact, Trait("Conformance", "COMP-017")]
    public void COMP_017_User_Predicate()
    {
        var items = new[] { "a", "bb", "ccc" };
        using var s = new SearchableState<string>(
            () => items,
            (i, t) => i.Length > t.Length,
            debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "bb";
        s.Search();
        snap.Last().Should().Equal("ccc");
    }

    [Fact, Trait("Conformance", "COMP-018")]
    public void COMP_018_Recompute_On_Items_Change()
    {
        var items = new List<string> { "one" };
        using var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        items.Add("two");
        s.Search();
        snap.Last().Should().Equal("one", "two");
    }

    [Fact, Trait("Conformance", "GRP-007")]
    public void GRP_007_Defaults_Group_Context()
    {
        var items = new[] { "x", "y" };
        using var s = new SearchableState<string>(
            () => items, CISubstr, debounce: TimeSpan.Zero);
        s.SearchTerm.Should().Be("");
    }

    [Fact, Trait("Conformance", "GRP-008")]
    public void GRP_008_Term_Recompute_Group_Context()
    {
        var items = new[] { "x", "yx", "z" };
        using var s = new SearchableState<string>(
            () => items, CISubstr, debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "x";
        snap.Last().Should().Equal("x", "yx");
    }

    [Fact, Trait("Conformance", "GRP-009")]
    public void GRP_009_Search_Forces_Group_Context()
    {
        var items = new[] { "a", "b" };
        using var s = new SearchableState<string>(
            () => items,
            (i, t) => t == "" || i == t,
            debounce: TimeSpan.FromSeconds(1));
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "b";
        s.Search();
        snap.Last().Should().Equal("b");
    }

    [Fact, Trait("Conformance", "GRP-010")]
    public void GRP_010_User_Predicate_Group_Context()
    {
        var items = new[] { 1, 2, 3, 4 };
        using var s = new SearchableState<int>(
            () => items,
            (i, t) => i > (int.TryParse(t, out var n) ? n : 0),
            debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<int>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        s.SearchTerm = "2";
        s.Search();
        snap.Last().Should().Equal(3, 4);
    }

    // ----- Dispose path — not a conformance ID, but a regression guard for
    // the _disposed idempotence guard and the Subject completions in Dispose().
    [Fact]
    public void SearchableState_Dispose_IsIdempotent()
    {
        var items = new[] { "a" };
        var s = new SearchableState<string>(() => items, CISubstr, debounce: TimeSpan.Zero);
        s.Dispose();
        // Second call must be a no-op (no double-OnCompleted on the BehaviorSubject).
        Action act = () => s.Dispose();
        act.Should().NotThrow();
    }

    [Fact]
    public void SearchableState_Dispose_CompletesFilteredStream()
    {
        var items = new[] { "a" };
        var s = new SearchableState<string>(() => items, CISubstr, debounce: TimeSpan.Zero);
        var completed = false;
        using var sub = s.Filtered.Subscribe(_ => { }, () => completed = true);
        s.Dispose();
        completed.Should().BeTrue();
    }

    // ----- SearchTerm setter: equality guard — regression guard for the
    // early-return in SearchableState.SearchTerm. Spec wording: "emission on a new value".
    [Fact]
    public void SearchableState_SearchTerm_Setter_Skips_NoOp_ReSet()
    {
        var items = new[] { "apple", "banana" };
        using var s = new SearchableState<string>(
            () => items, CISubstr, debounce: TimeSpan.Zero);
        var snap = new List<IReadOnlyList<string>>();
        using var sub = s.Filtered.Subscribe(snap.Add);
        var initial = snap.Count;

        s.SearchTerm = "appl";
        var afterFirst = snap.Count;
        afterFirst.Should().BeGreaterThan(initial, "first set must emit");

        s.SearchTerm = "appl";  // same value
        snap.Count.Should().Be(afterFirst,
            "setting SearchTerm to the same value must NOT trigger a recompute");
    }

    [Fact, Trait("Conformance", "SRCH-001")]
    public void SRCH_001_Source_Signal_Refreshes_Unchanged_Term()
    {
        var items = new List<string> { "one" };
        using var sourceChanges = new Subject<Unit>();
        using var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        using var subscription = s.Filtered.Subscribe(snapshots.Add);
        var before = snapshots.Count;

        items.Add("two");
        sourceChanges.OnNext(Unit.Default);

        snapshots.Should().HaveCount(before + 1);
        snapshots.Last().Should().Equal("one", "two");
    }

    [Fact, Trait("Conformance", "SRCH-002")]
    public void SRCH_002_Source_Signal_Reads_Each_Latest_Ordered_Snapshot()
    {
        var items = new List<string> { "a", "b", "c" };
        using var sourceChanges = new Subject<Unit>();
        using var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        using var subscription = s.Filtered.Subscribe(snapshots.Add);

        items.RemoveAt(1);
        sourceChanges.OnNext(Unit.Default);
        snapshots.Last().Should().Equal("a", "c");

        items[1] = "replacement";
        sourceChanges.OnNext(Unit.Default);
        snapshots.Last().Should().Equal("a", "replacement");

        items.Clear();
        items.Add("reset-1");
        items.Add("reset-2");
        items.Add("reset-3");
        sourceChanges.OnNext(Unit.Default);
        snapshots.Last().Should().Equal("reset-1", "reset-2", "reset-3");

        items.Reverse();
        sourceChanges.OnNext(Unit.Default);
        snapshots.Last().Should().Equal("reset-3", "reset-2", "reset-1");
    }

    [Fact, Trait("Conformance", "SRCH-003")]
    public void SRCH_003_Pulses_Preserve_Equality_And_Upstream_Coalescing()
    {
        var items = new List<string> { "same" };
        using var sourceChanges = new Subject<Unit>();
        using var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        using var subscription = s.Filtered.Subscribe(snapshots.Add);
        var before = snapshots.Count;

        sourceChanges.OnNext(Unit.Default);
        sourceChanges.OnNext(Unit.Default);
        snapshots.Should().HaveCount(before + 2);

        items.Add("batched-1");
        items.Add("batched-2");
        sourceChanges.OnNext(Unit.Default);
        snapshots.Should().HaveCount(before + 3);
        snapshots.Last().Should().Equal("same", "batched-1", "batched-2");
    }

    [Fact, Trait("Conformance", "SRCH-004")]
    public void SRCH_004_Source_Refresh_Does_Not_Reset_Pending_Term_Debounce()
    {
        var scheduler = new TestScheduler();
        var items = new List<string> { "alpha", "beta" };
        using var sourceChanges = new Subject<Unit>();
        using var s = new SearchableState<string>(
            () => items,
            CISubstr,
            debounce: TimeSpan.FromTicks(10),
            scheduler: scheduler,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        using var subscription = s.Filtered.Subscribe(snapshots.Add);

        s.SearchTerm = "alp";
        items.Add("alpine");
        var beforeSignal = snapshots.Count;
        sourceChanges.OnNext(Unit.Default);

        snapshots.Should().HaveCount(beforeSignal + 1);
        snapshots.Last().Should().Equal("alpha", "alpine");

        scheduler.AdvanceBy(9);
        snapshots.Should().HaveCount(beforeSignal + 1);
        scheduler.AdvanceBy(1);
        snapshots.Should().HaveCount(beforeSignal + 2);
        snapshots.Last().Should().Equal("alpha", "alpine");
    }

    [Fact, Trait("Conformance", "SRCH-005")]
    public void SRCH_005_Source_Error_Is_Isolated_From_Manual_Search()
    {
        var items = new List<string> { "one" };
        using var sourceChanges = new Subject<Unit>();
        using var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        var filteredErrored = false;
        var filteredCompleted = false;
        using var subscription = s.Filtered.Subscribe(
            snapshots.Add,
            _ => filteredErrored = true,
            () => filteredCompleted = true);

        sourceChanges.OnError(new InvalidOperationException("source failed"));
        items.Add("two");
        s.Search();

        filteredErrored.Should().BeFalse();
        filteredCompleted.Should().BeFalse();
        snapshots.Last().Should().Equal("one", "two");
    }

    [Fact, Trait("Conformance", "SRCH-006")]
    public void SRCH_006_Dispose_Cancels_Source_Once_Without_Owning_It()
    {
        var subscribeCount = 0;
        var disposeCount = 0;
        IObserver<Unit>? sourceObserver = null;
        var sourceChanges = Observable.Create<Unit>(observer =>
        {
            subscribeCount++;
            sourceObserver = observer;
            return Disposable.Create(() => disposeCount++);
        });
        var items = new List<string> { "one" };
        var s = new SearchableState<string>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero,
            sourceChanged: sourceChanges);
        var snapshots = new List<IReadOnlyList<string>>();
        using var filteredSubscription = s.Filtered.Subscribe(snapshots.Add);

        s.Dispose();
        s.Dispose();
        sourceObserver!.OnNext(Unit.Default);

        subscribeCount.Should().Be(1);
        disposeCount.Should().Be(1);
        snapshots.Should().HaveCount(1);

        using var independentSubscription = sourceChanges.Subscribe(_ => { });
        subscribeCount.Should().Be(2, "disposing SearchableState must not dispose the signal");
    }

    [Fact, Trait("Conformance", "SRCH-007")]
    public void SRCH_007_Omitted_Signal_Preserves_Explicit_Refresh_And_Item_Ownership()
    {
        var first = new OwnedSearchItem("one");
        var second = new OwnedSearchItem("two");
        var items = new List<OwnedSearchItem> { first };
        var s = new SearchableState<OwnedSearchItem>(
            () => items,
            (_, _) => true,
            debounce: TimeSpan.Zero);
        var snapshots = new List<IReadOnlyList<OwnedSearchItem>>();
        using var subscription = s.Filtered.Subscribe(snapshots.Add);
        var beforeMutation = snapshots.Count;

        items.Add(second);
        snapshots.Should().HaveCount(beforeMutation);

        s.Search();
        snapshots.Last().Should().Equal(first, second);
        s.Dispose();

        first.DisposeCount.Should().Be(0);
        second.DisposeCount.Should().Be(0);
    }
}
