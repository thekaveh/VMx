using FluentAssertions;
using VMx.Capabilities;
using VMx.Collections;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: COL-016..COL-021 — PagedComposition&lt;TVM&gt;.
/// See spec/21-collections.md §5 and ADR-0023.
/// </summary>
public class COL_016_to_021_PagedCompositionTests
{
    // ── COL-016 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-016: PagedComposition clamps CurrentPageIndex when source shrinks.
    ///
    /// Given a PagedComposition wrapping a 10-item source with PageSize == 3
    /// and CurrentPageIndex == 2 (last page)
    /// When items are removed from the source until 4 items remain (2 full pages)
    /// Then PageCount == 2 and CurrentPageIndex is clamped to 1.
    /// </summary>
    [Fact, Trait("Conformance", "COL-016")]
    public void COL_016_ClampsCurrentPageIndex_WhenSourceShrinks()
    {
        // Arrange: 10-item source, PageSize=3 → PageCount=4 (ceil(10/3))
        var source = new ObservableList<string>();
        for (int i = 0; i < 10; i++) source.Add($"item{i}");

        using var sut = new PagedComposition<string>(source, pageSize: 3);
        sut.PageCount.Should().Be(4);   // ceil(10/3) = 4

        // Navigate to page index 2 (third page)
        sut.CurrentPageIndex = 2;
        sut.CurrentPageIndex.Should().Be(2);

        // Act: remove items until only 4 remain (indices 0..3)
        while (source.Count > 4) source.RemoveAt(source.Count - 1);

        // Assert: PageCount drops to 2 (ceil(4/3)) and index re-clamps to 1
        sut.PageCount.Should().Be(2);
        sut.CurrentPageIndex.Should().Be(1);
    }

    // ── COL-017 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-017: PagedComposition PageCount derivation under add and remove.
    ///
    /// Given PageSize == 5, source starts empty, then 5 items added, then 1 more.
    /// PageCount: 0 → 1 → 2. Removing 1 item → PageCount drops back to 1.
    /// </summary>
    [Fact, Trait("Conformance", "COL-017")]
    public void COL_017_PageCount_DerivationUnderAddAndRemove()
    {
        var source = new ObservableList<int>();
        using var sut = new PagedComposition<int>(source, pageSize: 5);

        // Empty source + paging enabled → PageCount == 0 (spec §5.4)
        sut.PageCount.Should().Be(0);

        // Add 5 items → exactly one page
        for (int i = 0; i < 5; i++) source.Add(i);
        sut.PageCount.Should().Be(1);

        // Add 1 more → 6 items → 2 pages
        source.Add(99);
        sut.PageCount.Should().Be(2);

        // Remove 1 item → 5 items → back to 1 page
        source.Remove(99);
        sut.PageCount.Should().Be(1);
    }

    // ── COL-018 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-018: PagedComposition navigation no-ops at bounds.
    ///
    /// Given PageSize==3 over an 8-item source (PageCount==3):
    /// MoveToFirstPage at index 0 is a no-op;
    /// MoveToLastPage at last page is a no-op;
    /// MoveToNextPage at last page is a no-op;
    /// MoveToPreviousPage at first page is a no-op.
    /// </summary>
    [Fact, Trait("Conformance", "COL-018")]
    public void COL_018_Navigation_NoOpsAtBounds()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 8; i++) source.Add(i);

        using var sut = new PagedComposition<int>(source, pageSize: 3);
        sut.PageCount.Should().Be(3);   // ceil(8/3) = 3

        // MoveToFirstPage when already at 0 is a no-op
        sut.CurrentPageIndex.Should().Be(0);
        sut.MoveToFirstPage();
        sut.CurrentPageIndex.Should().Be(0);

        // MoveToPreviousPage at lower bound is a no-op
        sut.MoveToPreviousPage();
        sut.CurrentPageIndex.Should().Be(0);

        // Navigate to last page
        sut.MoveToLastPage();
        sut.CurrentPageIndex.Should().Be(2);

        // MoveToLastPage when already there is a no-op
        sut.MoveToLastPage();
        sut.CurrentPageIndex.Should().Be(2);

        // MoveToNextPage at upper bound is a no-op
        sut.MoveToNextPage();
        sut.CurrentPageIndex.Should().Be(2);
    }

    // ── COL-019 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-019: PagedComposition PageSize==0 passes through all items.
    ///
    /// Given a 7-item source with PageSize==0:
    /// IsPagingEnabled == false, PageCount == 1, CurrentPageIndex == 0,
    /// Items yields all 7 items.
    /// </summary>
    [Fact, Trait("Conformance", "COL-019")]
    public void COL_019_PageSizeZero_PassesThroughAllItems()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 7; i++) source.Add(i);

        using var sut = new PagedComposition<int>(source, pageSize: 0);

        sut.IsPagingEnabled.Should().BeFalse();
        sut.PageCount.Should().Be(1);
        sut.CurrentPageIndex.Should().Be(0);
        sut.Items.Should().BeEquivalentTo(Enumerable.Range(0, 7));
    }

    // ── COL-020 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-020: PagedComposition empty-source behavior.
    ///
    /// Given an empty source with PageSize==5:
    /// PageCount == 0, CurrentPageIndex == 0, Items is empty,
    /// all four navigation verbs are no-ops.
    /// </summary>
    [Fact, Trait("Conformance", "COL-020")]
    public void COL_020_EmptySource_Behavior()
    {
        var source = new ObservableList<string>();
        using var sut = new PagedComposition<string>(source, pageSize: 5);

        sut.PageCount.Should().Be(0);
        sut.CurrentPageIndex.Should().Be(0);
        sut.Items.Should().BeEmpty();

        // All navigation verbs are no-ops — must not throw
        var act = () =>
        {
            sut.MoveToFirstPage();
            sut.MoveToPreviousPage();
            sut.MoveToNextPage();
            sut.MoveToLastPage();
        };
        act.Should().NotThrow();

        sut.CurrentPageIndex.Should().Be(0);
    }

    // ── COL-021 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// COL-021: PagedComposition composition with SearchableState.
    ///
    /// Filter-first-then-page ordering (spec §6.1):
    /// PagedComposition takes the SearchableState filtered view as its source.
    /// PageCount is computed over the filtered count, not the total source count.
    /// </summary>
    [Fact, Trait("Conformance", "COL-021")]
    public void COL_021_CompositionWith_SearchableState()
    {
        // Source: 10 items. Items named "Alpha0".."Alpha3" start with 'A' (4 items);
        // the rest start with 'Z'.
        var items = new List<string>();
        for (int i = 0; i < 4; i++) items.Add($"Alpha{i}");
        for (int i = 0; i < 6; i++) items.Add($"Zeta{i}");

        // SearchableState: filter by items whose first char matches the search term
        // (empty term → all pass; "A" → only Alpha items pass).
        var searchable = new SearchableState<string>(
            items: () => items,
            predicate: (item, term) =>
                string.IsNullOrEmpty(term) || item.StartsWith(term, StringComparison.OrdinalIgnoreCase),
            debounce: TimeSpan.Zero);

        // Wire PagedComposition over the filtered view.
        // SearchableState.Filtered is an observable — we track the current snapshot.
        IReadOnlyList<string> filteredSnapshot = [];
        searchable.Filtered.Subscribe(snap => filteredSnapshot = snap);

        // PagedComposition takes a lazy-evaluated source: always reads from the
        // current filtered snapshot.
        using var sut = new PagedComposition<string>(
            source: new LazySource<string>(() => filteredSnapshot),
            pageSize: 3);

        // With empty search term all 10 items pass → ceil(10/3) = 4 pages
        sut.PageCount.Should().Be(4);

        // Apply search term "A" → only 4 Alpha items pass → ceil(4/3) = 2 pages
        searchable.SearchTerm = "A";
        searchable.Search();  // force synchronous recompute (debounce=0)

        // Notify the PagedComposition that its source changed (simulate via clamping)
        sut.CurrentPageIndex = sut.CurrentPageIndex; // no-op but triggers recalc
        sut.PageCount.Should().Be(2);   // ceil(4/3)

        // Page 0 should yield the first 3 filtered items
        sut.CurrentPageIndex = 0;
        var expectedPage0 = new List<string> { "Alpha0", "Alpha1", "Alpha2" };
        sut.Items.Should().BeEquivalentTo(expectedPage0);

        // Items on page 0 must NOT include any Zeta items
        sut.Items.Should().NotContain(s => s.StartsWith("Zeta"));
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// <summary>
    /// Thin IReadOnlyCollection wrapper over a lazy factory, so that
    /// PagedComposition always reads the live filtered snapshot without
    /// the composition needing to know about the SearchableState internals.
    /// </summary>
    private sealed class LazySource<T> : IReadOnlyCollection<T>
    {
        private readonly Func<IReadOnlyList<T>> _factory;
        public LazySource(Func<IReadOnlyList<T>> factory) => _factory = factory;
        public int Count => _factory().Count;
        public IEnumerator<T> GetEnumerator() => _factory().GetEnumerator();
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
