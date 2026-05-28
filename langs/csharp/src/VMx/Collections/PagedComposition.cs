using System.Collections.Specialized;
using System.ComponentModel;
using VMx.Capabilities;

namespace VMx.Collections;

/// <summary>
/// Decorates any <see cref="IEnumerable{TVM}"/> source with paged-view
/// semantics, implementing <see cref="IPageable"/>.
///
/// <para>
/// The underlying source is never mutated; this class computes a read-only
/// slice on demand. If the source also implements
/// <see cref="INotifyCollectionChanged"/>, mutations are observed and
/// <see cref="PageCount"/> / <see cref="Items"/> are updated automatically.
/// </para>
///
/// <para>
/// <see cref="PageSize"/> = 0 disables paging: all source items appear on a
/// single page (<see cref="PageCount"/> = 1, <see cref="IsPagingEnabled"/> = false).
/// </para>
///
/// <para>
/// Empty source with <see cref="PageSize"/> &gt; 0: <see cref="PageCount"/> = 0,
/// <see cref="CurrentPageIndex"/> is clamped to 0, <see cref="Items"/> is empty.
/// </para>
///
/// See spec/21-collections.md §5 and ADR-0023.
/// </summary>
/// <typeparam name="TVM">Element type.</typeparam>
public sealed class PagedComposition<TVM> : IPageable, INotifyPropertyChanged, IDisposable
{
    private readonly IEnumerable<TVM> _source;
    private int _pageSize;
    private int _currentPageIndex;
    private bool _disposed;

    /// <summary>
    /// Creates a new <see cref="PagedComposition{TVM}"/> over
    /// <paramref name="source"/> with an initial <see cref="PageSize"/> of
    /// <paramref name="pageSize"/>.
    /// </summary>
    /// <param name="source">The source sequence to page over.</param>
    /// <param name="pageSize">
    /// Initial page size (default 0 = paging disabled).
    /// Negative values are clamped to 0.
    /// </param>
    public PagedComposition(IEnumerable<TVM> source, int pageSize = 0)
    {
        _source = source ?? throw new ArgumentNullException(nameof(source));
        _pageSize = pageSize < 0 ? 0 : pageSize;
        _currentPageIndex = 0;

        if (source is INotifyCollectionChanged ncc)
            ncc.CollectionChanged += OnSourceCollectionChanged;
    }

    // ── IPageable ─────────────────────────────────────────────────────────────

    /// <inheritdoc/>
    public int PageSize
    {
        get => _pageSize;
        set
        {
            var clamped = value < 0 ? 0 : value;
            if (_pageSize == clamped) return;
            _pageSize = clamped;
            // Re-clamp CurrentPageIndex after page-size change
            _currentPageIndex = ClampIndex(_currentPageIndex);
            OnPropertyChanged(nameof(PageSize));
            OnPropertyChanged(nameof(IsPagingEnabled));
            OnPropertyChanged(nameof(PageCount));
            OnPropertyChanged(nameof(CurrentPageIndex));
            OnPropertyChanged(nameof(Items));
        }
    }

    /// <inheritdoc/>
    public int CurrentPageIndex
    {
        get => _currentPageIndex;
        set
        {
            var clamped = ClampIndex(value);
            if (_currentPageIndex == clamped) return;
            _currentPageIndex = clamped;
            OnPropertyChanged(nameof(CurrentPageIndex));
            OnPropertyChanged(nameof(Items));
        }
    }

    /// <inheritdoc/>
    public int PageCount
    {
        get
        {
            if (_pageSize == 0) return 1;
            var count = SourceCount();
            // Spec §5.4: empty source → PageCount == 0 (not max(1, …))
            return count == 0 ? 0 : (int)Math.Ceiling((double)count / _pageSize);
        }
    }

    /// <inheritdoc/>
    public bool IsPagingEnabled => _pageSize > 0;

    /// <inheritdoc/>
    public void MoveToFirstPage()
    {
        if (_currentPageIndex == 0) return;
        _currentPageIndex = 0;
        OnPropertyChanged(nameof(CurrentPageIndex));
        OnPropertyChanged(nameof(Items));
    }

    /// <inheritdoc/>
    public void MoveToPreviousPage()
    {
        if (_currentPageIndex <= 0) return;
        _currentPageIndex--;
        OnPropertyChanged(nameof(CurrentPageIndex));
        OnPropertyChanged(nameof(Items));
    }

    /// <inheritdoc/>
    public void MoveToNextPage()
    {
        var max = PageCount - 1;
        if (_currentPageIndex >= max) return;
        _currentPageIndex++;
        OnPropertyChanged(nameof(CurrentPageIndex));
        OnPropertyChanged(nameof(Items));
    }

    /// <inheritdoc/>
    public void MoveToLastPage()
    {
        var last = PageCount - 1;
        if (_currentPageIndex >= last) return;
        _currentPageIndex = last;
        OnPropertyChanged(nameof(CurrentPageIndex));
        OnPropertyChanged(nameof(Items));
    }

    // ── PagedComposition-specific surface ─────────────────────────────────────

    /// <summary>The decorated source sequence (never mutated by this class).</summary>
    public IEnumerable<TVM> Source => _source;

    /// <summary>
    /// The items on the current page.  Re-enumerated on each access.
    /// Returns an empty sequence when the source is empty or
    /// <see cref="PageSize"/> is 0 but the source is also empty.
    /// </summary>
    public IEnumerable<TVM> Items
    {
        get
        {
            if (_pageSize == 0) return _source;

            var count = SourceCount();
            if (count == 0) return Enumerable.Empty<TVM>();

            var skip = _currentPageIndex * _pageSize;
            return _source.Skip(skip).Take(_pageSize);
        }
    }

    /// <summary>
    /// The number of items on the current page (not the total source count).
    /// </summary>
    public int Count => Items.Count();

    // ── INotifyPropertyChanged ────────────────────────────────────────────────

    /// <summary>Fires when a property of this composition changes.</summary>
    public event PropertyChangedEventHandler? PropertyChanged;

    // ── Internal ──────────────────────────────────────────────────────────────

    private void OnSourceCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        // Re-clamp: if CurrentPageIndex is now beyond the (possibly shrunken) PageCount
        var clamped = ClampIndex(_currentPageIndex);
        var indexChanged = clamped != _currentPageIndex;
        if (indexChanged) _currentPageIndex = clamped;

        OnPropertyChanged(nameof(PageCount));
        if (indexChanged) OnPropertyChanged(nameof(CurrentPageIndex));
        OnPropertyChanged(nameof(Items));
    }

    private int SourceCount()
    {
        if (_source is IReadOnlyCollection<TVM> roc) return roc.Count;
        if (_source is ICollection<TVM> col) return col.Count;
        return _source.Count();
    }

    private int ClampIndex(int index)
    {
        // When PageCount == 0 (empty source + paging enabled), index stays at 0
        var max = Math.Max(0, PageCount - 1);
        if (index < 0) return 0;
        if (index > max) return max;
        return index;
    }

    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    /// <summary>Detaches from the source's <see cref="INotifyCollectionChanged"/> event.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        if (_source is INotifyCollectionChanged ncc)
            ncc.CollectionChanged -= OnSourceCollectionChanged;
    }
}
