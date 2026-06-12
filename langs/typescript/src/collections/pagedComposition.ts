/**
 * PagedComposition<TVM> — paged-view decorator for any source array or factory.
 *
 * Decorates any source (array, ObservableList, or lazy factory) with
 * paged-view semantics.  Implements IPageable (CAP-022, ADR-0023).
 *
 * The source is never mutated; this class computes a read-only slice on
 * demand.  If the source is an ObservableList, mutations are observed
 * automatically so pageCount and items stay in sync.
 *
 * pageSize = 0 disables paging: all source items appear on a single page
 * (pageCount = 1, isPagingEnabled = false).
 *
 * Empty source with pageSize > 0: pageCount = 0, currentPageIndex = 0,
 * items = [].  (Spec §5.4.)
 *
 * See spec/21-collections.md §5 and ADR-0023.
 */

import { Observable, Subject, Subscription } from "rxjs";
import type { IPageable } from "../capabilities/pageable.js";

// Source type: an array, an iterable, or a zero-arg factory.
export type PagedCompositionSource<T> =
  | readonly T[]
  | T[]
  | Iterable<T>
  | (() => Iterable<T>);

export class PagedComposition<TVM> implements IPageable {
  readonly #rawSource: PagedCompositionSource<TVM>;
  readonly #factory: () => Iterable<TVM>;
  #pageSize: number;
  #currentPageIndex = 0;

  readonly #propertyChanged = new Subject<string>();
  readonly #subscriptions: Subscription[] = [];

  /**
   * @param source  Source array, iterable, or zero-arg factory.
   * @param pageSize  Initial page size (default 0 = paging disabled).
   *                  Negative values are clamped to 0.
   */
  constructor(
    source: PagedCompositionSource<TVM>,
    pageSize = 0,
  ) {
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (source == null) throw new TypeError("source must not be null/undefined");
    this.#rawSource = source;
    this.#pageSize = Math.max(0, pageSize);

    // Normalise source into a zero-arg factory for uniform access.
    if (typeof source === "function") {
      this.#factory = source as () => Iterable<TVM>;
    } else {
      this.#factory = () => source as Iterable<TVM>;
    }

    // Subscribe to mutation events if the source supports them (duck-typing:
    // ObservableList exposes .itemAdded / .itemRemoved / .itemReplaced /
    // .reset — replace mutates page contents too).
    const src = source as unknown as Record<string, unknown>;
    for (const key of ["itemAdded", "itemRemoved", "itemReplaced", "reset"] as const) {
      if (src[key] instanceof Observable) {
        this.#subscriptions.push(
          (src[key] as Observable<unknown>).subscribe({
            next: () => this.#onSourceMutated(),
          }),
        );
      }
    }
  }

  // ── IPageable ──────────────────────────────────────────────────────────────

  get pageSize(): number {
    return this.#pageSize;
  }

  set pageSize(value: number) {
    const clamped = Math.max(0, value);
    if (this.#pageSize === clamped) return;
    this.#pageSize = clamped;
    this.#currentPageIndex = this.#clampIndex(this.#currentPageIndex);
    this.#notify("pageSize");
    this.#notify("isPagingEnabled");
    this.#notify("pageCount");
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  get currentPageIndex(): number {
    return this.#currentPageIndex;
  }

  set currentPageIndex(value: number) {
    const clamped = this.#clampIndex(value);
    if (this.#currentPageIndex === clamped) return;
    this.#currentPageIndex = clamped;
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  get pageCount(): number {
    if (this.#pageSize === 0) return 1;
    const n = this.#sourceLength();
    // Spec §5.4: empty source → pageCount = 0 (not max(1, …))
    if (n === 0) return 0;
    return Math.ceil(n / this.#pageSize);
  }

  get isPagingEnabled(): boolean {
    return this.#pageSize > 0;
  }

  moveToFirstPage(): void {
    if (this.#currentPageIndex === 0) return;
    this.#currentPageIndex = 0;
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  moveToPreviousPage(): void {
    if (this.#currentPageIndex <= 0) return;
    this.#currentPageIndex--;
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  moveToNextPage(): void {
    const max = this.pageCount - 1;
    if (this.#currentPageIndex >= max) return;
    this.#currentPageIndex++;
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  moveToLastPage(): void {
    const last = this.pageCount - 1;
    if (this.#currentPageIndex >= last) return;
    this.#currentPageIndex = last;
    this.#notify("currentPageIndex");
    this.#notify("items");
  }

  // ── PagedComposition-specific surface ─────────────────────────────────────

  /** The raw source passed to the constructor (never mutated). */
  get source(): PagedCompositionSource<TVM> {
    return this.#rawSource;
  }

  /**
   * The items on the current page.
   *
   * Returns all source items when paging is disabled (pageSize = 0).
   * Returns an empty array when the source is empty.
   */
  get items(): TVM[] {
    const all = [...this.#factory()];
    if (this.#pageSize === 0) return all;
    if (all.length === 0) return [];
    const start = this.#currentPageIndex * this.#pageSize;
    return all.slice(start, start + this.#pageSize);
  }

  /** Number of items on the current page (not the total source count). */
  get count(): number {
    return this.items.length;
  }

  /**
   * Observable that emits property names whenever they change.
   * Useful for bindings that need to react to page navigation or source mutations.
   */
  get propertyChanged(): Observable<string> {
    return this.#propertyChanged.asObservable();
  }

  /** Unsubscribes from source observables. Idempotent. */
  dispose(): void {
    for (const sub of this.#subscriptions) sub.unsubscribe();
    this.#subscriptions.length = 0;
    this.#propertyChanged.complete();
  }

  // ── Internal helpers ───────────────────────────────────────────────────────

  #sourceLength(): number {
    const src = this.#factory();
    if (Array.isArray(src)) return src.length;
    let count = 0;
    for (const _ of src) count++;
    return count;
  }

  #clampIndex(index: number): number {
    // When pageCount == 0 (empty source + paging enabled), index stays at 0
    const max = Math.max(0, this.pageCount - 1);
    if (index < 0) return 0;
    if (index > max) return max;
    return index;
  }

  #onSourceMutated(): void {
    const clamped = this.#clampIndex(this.#currentPageIndex);
    const indexChanged = clamped !== this.#currentPageIndex;
    if (indexChanged) this.#currentPageIndex = clamped;
    this.#notify("pageCount");
    if (indexChanged) this.#notify("currentPageIndex");
    this.#notify("items");
  }

  #notify(name: string): void {
    this.#propertyChanged.next(name);
  }
}
