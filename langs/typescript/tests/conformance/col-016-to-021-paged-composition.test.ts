// Conformance tests: COL-016..COL-021 — PagedComposition<TVM>.
// See spec/21-collections.md §5 and ADR-0023.

import { describe, expect, it } from "vitest";
import { SearchableState } from "../../src/capabilities/searchableState.js";
import { ObservableList } from "../../src/collections/observableList.js";
import { PagedComposition } from "../../src/collections/pagedComposition.js";

// ── COL-016 ───────────────────────────────────────────────────────────────────

describe("COL-016", () => {
  it("PagedComposition clamps currentPageIndex to [0, pageCount-1] when source shrinks", () => {
    // Given: 10-item source, pageSize=3 → pageCount=4 (ceil(10/3))
    const source = new ObservableList<string>();
    for (let i = 0; i < 10; i++) source.push(`item${String(i)}`);

    const sut = new PagedComposition<string>(source, 3);
    expect(sut.pageCount).toBe(4);

    // Navigate to page index 2 (third page)
    sut.currentPageIndex = 2;
    expect(sut.currentPageIndex).toBe(2);

    // Remove items until only 4 remain
    while (source.length > 4) source.removeAt(source.length - 1);

    // PageCount drops to 2 (ceil(4/3)) and index re-clamps to 1
    expect(sut.pageCount).toBe(2);
    expect(sut.currentPageIndex).toBe(1);

    sut.dispose();
  });

  it("rejects non-finite and fractional paging state before mutation", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);

    for (const invalid of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, 1.5]) {
      expect(() => new PagedComposition(source, invalid)).toThrow(RangeError);
    }

    const sut = new PagedComposition(source, 2);
    sut.currentPageIndex = 1;
    const changed: string[] = [];
    const sub = sut.propertyChanged.subscribe((name) => changed.push(name));

    for (const invalid of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, 2.5]) {
      expect(() => {
        sut.pageSize = invalid;
      }).toThrow(RangeError);
      expect(sut.pageSize).toBe(2);
      expect(sut.currentPageIndex).toBe(1);

      expect(() => {
        sut.currentPageIndex = invalid;
      }).toThrow(RangeError);
      expect(sut.currentPageIndex).toBe(1);
    }

    expect(changed).toEqual([]);
    sub.unsubscribe();
    sut.dispose();
  });
});

// ── COL-017 ───────────────────────────────────────────────────────────────────

describe("COL-017", () => {
  it("PagedComposition pageCount equals ceil(sourceCount / pageSize) and updates on mutations", () => {
    // Given: pageSize=5, empty source
    const source = new ObservableList<number>();
    const sut = new PagedComposition<number>(source, 5);

    // Empty source + paging enabled → pageCount == 0 (spec §5.4)
    expect(sut.pageCount).toBe(0);

    // Add 5 items → exactly one page
    for (let i = 0; i < 5; i++) source.push(i);
    expect(sut.pageCount).toBe(1);

    // Add 1 more → 6 items → 2 pages
    source.push(99);
    expect(sut.pageCount).toBe(2);

    // Remove that item → back to 1 page
    source.pop();
    expect(sut.pageCount).toBe(1);

    sut.dispose();
  });
});

// ── COL-018 ───────────────────────────────────────────────────────────────────

describe("COL-018", () => {
  it("PagedComposition moveToFirstPage / moveToLastPage are no-ops when already at bounds", () => {
    // Given: pageSize=3 over 8 items → pageCount=3
    const source = new ObservableList<number>();
    for (let i = 0; i < 8; i++) source.push(i);

    const sut = new PagedComposition<number>(source, 3);
    expect(sut.pageCount).toBe(3);

    // MoveToFirstPage at index 0 is a no-op
    expect(sut.currentPageIndex).toBe(0);
    sut.moveToFirstPage();
    expect(sut.currentPageIndex).toBe(0);

    // MoveToPreviousPage at lower bound is a no-op
    sut.moveToPreviousPage();
    expect(sut.currentPageIndex).toBe(0);

    // Navigate to upper bound
    sut.moveToLastPage();
    expect(sut.currentPageIndex).toBe(2);

    // MoveToLastPage when already there is a no-op
    sut.moveToLastPage();
    expect(sut.currentPageIndex).toBe(2);

    // MoveToNextPage at upper bound is a no-op
    sut.moveToNextPage();
    expect(sut.currentPageIndex).toBe(2);

    sut.dispose();
  });
});

// ── COL-019 ───────────────────────────────────────────────────────────────────

describe("COL-019", () => {
  it("PagedComposition pageSize==0 disables paging and items yields the full source", () => {
    // Given: 7-item source with pageSize=0
    const source = new ObservableList<number>();
    for (let i = 0; i < 7; i++) source.push(i);

    const sut = new PagedComposition<number>(source, 0);

    expect(sut.isPagingEnabled).toBe(false);
    expect(sut.pageCount).toBe(1);
    expect(sut.currentPageIndex).toBe(0);
    expect(sut.items).toEqual([0, 1, 2, 3, 4, 5, 6]);

    sut.dispose();
  });
});

// ── COL-020 ───────────────────────────────────────────────────────────────────

describe("COL-020", () => {
  it("PagedComposition on empty source: pageCount==0, items empty, navigation is a no-op", () => {
    // Given: empty source with pageSize=5
    const source = new ObservableList<string>();
    const sut = new PagedComposition<string>(source, 5);

    expect(sut.pageCount).toBe(0);
    expect(sut.currentPageIndex).toBe(0);
    expect(sut.items).toEqual([]);

    // All navigation verbs are no-ops — must not throw
    expect(() => {
      sut.moveToFirstPage();
      sut.moveToPreviousPage();
      sut.moveToNextPage();
      sut.moveToLastPage();
    }).not.toThrow();

    expect(sut.currentPageIndex).toBe(0);

    sut.dispose();
  });
});

// ── COL-021 ───────────────────────────────────────────────────────────────────

describe("COL-021", () => {
  it("PagedComposition wrapping SearchableState filtered view pages the filtered count", () => {
    // Source: 10 items — 4 Alpha items, 6 Zeta items
    const items: string[] = [
      ...Array.from({ length: 4 }, (_, i) => `Alpha${String(i)}`),
      ...Array.from({ length: 6 }, (_, i) => `Zeta${String(i)}`),
    ];

    // SearchableState: empty term → all pass; "Alpha" → only Alpha items pass
    const searchable = new SearchableState<string>({
      items: () => items,
      predicate: (item, term) =>
        term === "" || item.toLowerCase().startsWith(term.toLowerCase()),
      debounceMs: 0,
    });

    // Track the current filtered snapshot
    let filteredSnapshot: readonly string[] = [];
    searchable.filtered.subscribe((snap) => {
      filteredSnapshot = snap;
    });

    // Force initial recompute
    searchable.search();

    // PagedComposition wraps a lazy factory that always reads the current snapshot
    const sut = new PagedComposition<string>(() => filteredSnapshot, 3);

    // With empty search term all 10 items pass → ceil(10/3) = 4 pages
    expect(sut.pageCount).toBe(4);

    // Apply search term → 4 Alpha items → ceil(4/3) = 2 pages
    searchable.searchTerm = "Alpha";
    searchable.search(); // force synchronous recompute (debounceMs=0)

    expect(sut.pageCount).toBe(2);

    // Page 0 should yield the first 3 filtered items
    sut.currentPageIndex = 0;
    expect(sut.items).toEqual(["Alpha0", "Alpha1", "Alpha2"]);

    // Items on page 0 must NOT include any Zeta items
    expect(sut.items.some((item) => item.startsWith("Zeta"))).toBe(false);

    sut.dispose();
    searchable.dispose();
  });
});
