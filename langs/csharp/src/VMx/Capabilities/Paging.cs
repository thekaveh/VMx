namespace VMx.Capabilities;

// Capability interface from spec/14-capabilities.md §2.10 and ADR-0023.
// Opt-in; not implemented by default by any core VM type.

/// <summary>
/// Capability: the implementer exposes a paged navigation surface over its
/// underlying data.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="PageSize"/> and <see cref="CurrentPageIndex"/> are mutable.
/// <see cref="PageCount"/> and <see cref="IsPagingEnabled"/> are derived.
/// </para>
/// <para>
/// Clamping contract (implementer responsibility, verified by CAP-022):
/// <list type="bullet">
///   <item>Setting <see cref="CurrentPageIndex"/> outside [0, PageCount-1]
///         clamps to the nearest bound.</item>
///   <item>Resizing <see cref="PageSize"/> must re-clamp
///         <see cref="CurrentPageIndex"/> if it falls out of range.</item>
///   <item>All navigation methods are no-ops when already at the respective
///         bound.</item>
/// </list>
/// </para>
/// <para>
/// When <see cref="PageSize"/> is 0 paging is disabled: every item fits in
/// a single page (<see cref="PageCount"/> == 1, <see cref="IsPagingEnabled"/>
/// == false).
/// </para>
/// </remarks>
public interface IPageable
{
    /// <summary>
    /// Number of items per page.  0 means "all items in one page" (paging
    /// disabled).  Must not be negative; implementers may clamp negative
    /// assignments to 0.
    /// </summary>
    int PageSize { get; set; }

    /// <summary>
    /// Zero-based index of the currently visible page.
    /// Setting a value outside [0, <see cref="PageCount"/>-1] must clamp to
    /// the nearest bound.
    /// </summary>
    int CurrentPageIndex { get; set; }

    /// <summary>
    /// Total number of pages.
    /// Derived as <c>max(1, ceil(itemCount / PageSize))</c> when
    /// <see cref="IsPagingEnabled"/> is true; 1 when paging is disabled.
    /// </summary>
    int PageCount { get; }

    /// <summary>Returns <see langword="true"/> when <see cref="PageSize"/> &gt; 0.</summary>
    bool IsPagingEnabled { get; }

    /// <summary>
    /// Sets <see cref="CurrentPageIndex"/> to 0.
    /// No-op when already at the first page.
    /// </summary>
    void MoveToFirstPage();

    /// <summary>
    /// Decrements <see cref="CurrentPageIndex"/> by 1.
    /// No-op when <see cref="CurrentPageIndex"/> is already 0.
    /// </summary>
    void MoveToPreviousPage();

    /// <summary>
    /// Increments <see cref="CurrentPageIndex"/> by 1.
    /// No-op when <see cref="CurrentPageIndex"/> is already
    /// <see cref="PageCount"/>-1.
    /// </summary>
    void MoveToNextPage();

    /// <summary>
    /// Sets <see cref="CurrentPageIndex"/> to <see cref="PageCount"/>-1.
    /// No-op when already at the last page.
    /// </summary>
    void MoveToLastPage();
}
