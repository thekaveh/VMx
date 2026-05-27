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
}
