//
// Paging capability micro-interface — `Pageable`.
//
// Ports langs/typescript/src/capabilities/pageable.ts. See
// spec/14-capabilities.md §2.10 and ADR-0023 / ADR-0057.
//
// `pageSize` and `currentPageIndex` are mutable; `pageCount` and
// `isPagingEnabled` are derived. Clamping is the implementer's responsibility
// (verified by CAP-022):
//   - `pageSize` clamps to ≥ 0; `pageSize == 0` disables paging
//     (`isPagingEnabled == false`, `pageCount == 1`).
//   - `pageCount` is `ceil(itemCount / pageSize)` when paging is enabled
//     (0 for an empty source), else 1.
//   - Setting `currentPageIndex` outside `[0, pageCount - 1]` clamps to the
//     nearest bound; resizing `pageSize` re-clamps it.
//   - The four navigation methods are no-ops when already at the bound.
//
// Swift idiom: bare protocol name (no `I`-prefix), camelCase members.
//
public protocol Pageable {
    /// Number of items per page. 0 means "all items in one page" (paging
    /// disabled); negative assignments clamp to 0.
    var pageSize: Int { get set }
    /// Zero-based index of the currently visible page. Assignments outside
    /// `[0, pageCount - 1]` clamp to the nearest bound.
    var currentPageIndex: Int { get set }
    /// Total number of pages: `ceil(itemCount / pageSize)` when paging is
    /// enabled (0 when the source is empty), 1 when paging is disabled.
    var pageCount: Int { get }
    /// `true` when `pageSize > 0`.
    var isPagingEnabled: Bool { get }
    /// Set `currentPageIndex` to 0. No-op when already at the first page.
    func moveToFirstPage()
    /// Decrement `currentPageIndex`. No-op when already 0.
    func moveToPreviousPage()
    /// Increment `currentPageIndex`. No-op when already at `pageCount - 1`.
    func moveToNextPage()
    /// Set `currentPageIndex` to `pageCount - 1`. No-op when already last.
    func moveToLastPage()
}
