// Paging capability contract. See spec/14-capabilities.md §2.10 and ADR-0023.

/**
 * IPageable capability: the implementer exposes a paged navigation surface
 * over its underlying data (CAP-022, ADR-0023).
 *
 * `pageSize` and `currentPageIndex` are mutable.
 * `pageCount` and `isPagingEnabled` are derived.
 *
 * Clamping contract (implementer responsibility, verified by CAP-022):
 * - Setting `currentPageIndex` outside `[0, pageCount-1]` must clamp to the
 *   nearest bound.
 * - Resizing `pageSize` must re-clamp `currentPageIndex` if out of range.
 * - All navigation methods are no-ops when already at the respective bound.
 *
 * When `pageSize` is 0 paging is disabled: every item fits in a single page
 * (`pageCount === 1`, `isPagingEnabled === false`).
 */
export interface IPageable {
  /**
   * Number of items per page.  0 means "all items in one page" (paging
   * disabled).  Must not be negative; implementers may clamp negative
   * assignments to 0.
   */
  pageSize: number;

  /**
   * Zero-based index of the currently visible page.
   * Setting a value outside `[0, pageCount-1]` must clamp to the nearest
   * bound.
   */
  currentPageIndex: number;

  /**
   * Total number of pages.
   * Derived as `ceil(itemCount / pageSize)` when paging is enabled
   * (0 when the source is empty); 1 when paging is disabled (`pageSize === 0`).
   */
  readonly pageCount: number;

  /** `true` when `pageSize > 0`. */
  readonly isPagingEnabled: boolean;

  /**
   * Sets `currentPageIndex` to 0.
   * No-op when already at the first page.
   */
  moveToFirstPage(): void;

  /**
   * Decrements `currentPageIndex` by 1.
   * No-op when `currentPageIndex` is already 0.
   */
  moveToPreviousPage(): void;

  /**
   * Increments `currentPageIndex` by 1.
   * No-op when `currentPageIndex` is already `pageCount - 1`.
   */
  moveToNextPage(): void;

  /**
   * Sets `currentPageIndex` to `pageCount - 1`.
   * No-op when already at the last page.
   */
  moveToLastPage(): void;
}
