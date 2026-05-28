using FluentAssertions;
using VMx.Collections;
using Xunit;

namespace VMx.Tests.Collections;

/// <summary>
/// Unit tests for <see cref="PagedComposition{TVM}"/>.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class PagedCompositionTests
{
    // ── Construction ──────────────────────────────────────────────────────────

    [Fact]
    public void Constructor_DefaultPageSize_IsZero()
    {
        var source = new ObservableList<int>();
        using var sut = new PagedComposition<int>(source);
        sut.PageSize.Should().Be(0);
        sut.IsPagingEnabled.Should().BeFalse();
    }

    [Fact]
    public void Constructor_NegativePageSize_ClampedToZero()
    {
        var source = new ObservableList<int>();
        using var sut = new PagedComposition<int>(source, pageSize: -5);
        sut.PageSize.Should().Be(0);
    }

    [Fact]
    public void Constructor_NullSource_Throws()
    {
        var act = () => new PagedComposition<int>(null!);
        act.Should().Throw<ArgumentNullException>();
    }

    // ── PageCount derivation ──────────────────────────────────────────────────

    [Theory]
    [InlineData(10, 3, 4)]  // ceil(10/3) = 4
    [InlineData(9, 3, 3)]   // ceil(9/3) = 3
    [InlineData(1, 5, 1)]   // ceil(1/5) = 1
    [InlineData(5, 5, 1)]   // ceil(5/5) = 1
    [InlineData(6, 5, 2)]   // ceil(6/5) = 2
    public void PageCount_ReflectsSourceCount(int itemCount, int pageSize, int expectedPageCount)
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < itemCount; i++) source.Add(i);

        using var sut = new PagedComposition<int>(source, pageSize: pageSize);
        sut.PageCount.Should().Be(expectedPageCount);
    }

    [Fact]
    public void PageCount_EmptySource_WithPagingEnabled_IsZero()
    {
        var source = new ObservableList<int>();
        using var sut = new PagedComposition<int>(source, pageSize: 5);
        sut.PageCount.Should().Be(0);
    }

    [Fact]
    public void PageCount_PageSizeZero_IsAlwaysOne()
    {
        var source = new ObservableList<int>();
        source.Add(1);
        source.Add(2);
        using var sut = new PagedComposition<int>(source, pageSize: 0);
        sut.PageCount.Should().Be(1);
    }

    // ── Items / slicing ───────────────────────────────────────────────────────

    [Fact]
    public void Items_FirstPage_YieldsCorrectSlice()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 10; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 3);

        sut.CurrentPageIndex = 0;
        sut.Items.Should().Equal(0, 1, 2);
    }

    [Fact]
    public void Items_LastPage_YieldsRemainder()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 10; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 3);

        sut.CurrentPageIndex = 3;   // 4th page: items 9..9
        sut.Items.Should().Equal(9);
    }

    [Fact]
    public void Items_PageSizeZero_YieldsAll()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 5; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 0);
        sut.Items.Should().Equal(0, 1, 2, 3, 4);
    }

    [Fact]
    public void Count_ReflectsCurrentPageItemCount()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 7; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 3);

        sut.CurrentPageIndex = 0;
        sut.Count.Should().Be(3);

        sut.CurrentPageIndex = 2;  // last page: only 1 item (7 mod 3)
        sut.Count.Should().Be(1);
    }

    // ── CurrentPageIndex clamping ─────────────────────────────────────────────

    [Fact]
    public void CurrentPageIndex_SetBeyondPageCount_ClampsToMax()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);   // PageCount=3

        sut.CurrentPageIndex = 99;
        sut.CurrentPageIndex.Should().Be(2);
    }

    [Fact]
    public void CurrentPageIndex_SetNegative_ClampsToZero()
    {
        var source = new ObservableList<int>();
        source.Add(1);
        using var sut = new PagedComposition<int>(source, pageSize: 1);

        sut.CurrentPageIndex = -1;
        sut.CurrentPageIndex.Should().Be(0);
    }

    // ── Navigation ────────────────────────────────────────────────────────────

    [Fact]
    public void MoveToFirstPage_SetsIndexToZero()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);
        sut.MoveToLastPage();
        sut.MoveToFirstPage();
        sut.CurrentPageIndex.Should().Be(0);
    }

    [Fact]
    public void MoveToLastPage_SetsIndexToPageCountMinus1()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);
        sut.MoveToLastPage();
        sut.CurrentPageIndex.Should().Be(2);
    }

    [Fact]
    public void MoveToNextPage_AdvancesIndex()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);
        sut.MoveToNextPage();
        sut.CurrentPageIndex.Should().Be(1);
    }

    [Fact]
    public void MoveToPreviousPage_DecrementsIndex()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);
        sut.MoveToLastPage();
        sut.MoveToPreviousPage();
        sut.CurrentPageIndex.Should().Be(1);
    }

    // ── PageSize mutation re-clamps CurrentPageIndex ──────────────────────────

    [Fact]
    public void PageSize_SettingLarger_ReclampsMayMoveIndex()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 10; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);  // PageCount=5

        sut.CurrentPageIndex = 4;
        sut.PageSize = 5;  // PageCount = 2 now; index 4 > max(1) → clamp to 1
        sut.CurrentPageIndex.Should().Be(1);
    }

    // ── INotifyPropertyChanged ────────────────────────────────────────────────

    [Fact]
    public void PropertyChanged_FiresOnCurrentPageIndexChange()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 6; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);

        var changed = new List<string?>();
        sut.PropertyChanged += (_, e) => changed.Add(e.PropertyName);

        sut.MoveToNextPage();

        changed.Should().Contain(nameof(sut.CurrentPageIndex));
        changed.Should().Contain(nameof(sut.Items));
    }

    [Fact]
    public void PropertyChanged_FiresOnSourceMutation()
    {
        var source = new ObservableList<int>();
        for (int i = 0; i < 3; i++) source.Add(i);
        using var sut = new PagedComposition<int>(source, pageSize: 2);

        var changed = new List<string?>();
        sut.PropertyChanged += (_, e) => changed.Add(e.PropertyName);

        source.Add(99);  // PageCount changes from 2 to 2 (no change), Items recomputed

        changed.Should().Contain(nameof(sut.PageCount));
    }

    // ── Source property ───────────────────────────────────────────────────────

    [Fact]
    public void Source_ReturnsOriginalSource()
    {
        var source = new ObservableList<int>();
        using var sut = new PagedComposition<int>(source, pageSize: 2);
        sut.Source.Should().BeSameAs(source);
    }

    // ── Dispose ───────────────────────────────────────────────────────────────

    [Fact]
    public void Dispose_IsIdempotent()
    {
        var source = new ObservableList<int>();
        source.Add(1);
        var sut = new PagedComposition<int>(source, pageSize: 1);
        sut.Dispose();
        var act = () => sut.Dispose();
        act.Should().NotThrow();
    }
}
