// Unit tests for PagedComposition<TVM>.
// Conformance-level tests live in tests/conformance/col-016-to-021-paged-composition.test.ts.

import { describe, expect, it } from "vitest";
import { ObservableList } from "../../src/collections/observableList.js";
import { PagedComposition } from "../../src/collections/pagedComposition.js";

// ── Construction ──────────────────────────────────────────────────────────────

describe("PagedComposition – construction", () => {
  it("defaults pageSize to 0", () => {
    const source = new ObservableList<number>();
    const sut = new PagedComposition(source);
    expect(sut.pageSize).toBe(0);
    expect(sut.isPagingEnabled).toBe(false);
    sut.dispose();
  });

  it("clamps negative pageSize to 0", () => {
    const source = new ObservableList<number>();
    const sut = new PagedComposition(source, -5);
    expect(sut.pageSize).toBe(0);
    sut.dispose();
  });

  it("throws when source is null", () => {
    expect(() => new PagedComposition(null as never)).toThrow(TypeError);
  });
});

// ── pageCount derivation ──────────────────────────────────────────────────────

describe("PagedComposition – pageCount", () => {
  it.each([
    [10, 3, 4], // ceil(10/3) = 4
    [9, 3, 3], // ceil(9/3) = 3
    [1, 5, 1], // ceil(1/5) = 1
    [5, 5, 1], // ceil(5/5) = 1
    [6, 5, 2], // ceil(6/5) = 2
  ])("pageCount(%i items, pageSize=%i) = %i", (itemCount, pageSize, expected) => {
    const source = new ObservableList<number>();
    for (let i = 0; i < itemCount; i++) source.push(i);
    const sut = new PagedComposition(source, pageSize);
    expect(sut.pageCount).toBe(expected);
    sut.dispose();
  });

  it("pageCount is 0 for empty source with paging enabled", () => {
    const source = new ObservableList<number>();
    const sut = new PagedComposition(source, 5);
    expect(sut.pageCount).toBe(0);
    sut.dispose();
  });

  it("pageCount is 1 when pageSize == 0", () => {
    const source = new ObservableList<number>();
    source.push(1);
    source.push(2);
    const sut = new PagedComposition(source, 0);
    expect(sut.pageCount).toBe(1);
    sut.dispose();
  });
});

// ── items / slicing ───────────────────────────────────────────────────────────

describe("PagedComposition – items", () => {
  it("first page yields correct slice", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 10; i++) source.push(i);
    const sut = new PagedComposition(source, 3);
    sut.currentPageIndex = 0;
    expect(sut.items).toEqual([0, 1, 2]);
    sut.dispose();
  });

  it("last page yields remainder items", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 10; i++) source.push(i);
    const sut = new PagedComposition(source, 3);
    sut.currentPageIndex = 3; // 4th page: only item 9
    expect(sut.items).toEqual([9]);
    sut.dispose();
  });

  it("pageSize==0 yields all items", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 5; i++) source.push(i);
    const sut = new PagedComposition(source, 0);
    expect(sut.items).toEqual([0, 1, 2, 3, 4]);
    sut.dispose();
  });

  it("count reflects current page item count", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 7; i++) source.push(i);
    const sut = new PagedComposition(source, 3);
    sut.currentPageIndex = 0;
    expect(sut.count).toBe(3);
    sut.currentPageIndex = 2; // last page: 1 item (7 mod 3)
    expect(sut.count).toBe(1);
    sut.dispose();
  });
});

// ── currentPageIndex clamping ─────────────────────────────────────────────────

describe("PagedComposition – clamping", () => {
  it("clamps currentPageIndex > pageCount-1 to max", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2); // pageCount=3
    sut.currentPageIndex = 99;
    expect(sut.currentPageIndex).toBe(2);
    sut.dispose();
  });

  it("clamps negative currentPageIndex to 0", () => {
    const source = new ObservableList<number>();
    source.push(1);
    const sut = new PagedComposition(source, 1);
    sut.currentPageIndex = -1;
    expect(sut.currentPageIndex).toBe(0);
    sut.dispose();
  });
});

// ── Navigation ────────────────────────────────────────────────────────────────

describe("PagedComposition – navigation", () => {
  it("moveToFirstPage sets index to 0", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2);
    sut.moveToLastPage();
    sut.moveToFirstPage();
    expect(sut.currentPageIndex).toBe(0);
    sut.dispose();
  });

  it("moveToLastPage sets index to pageCount-1", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2);
    sut.moveToLastPage();
    expect(sut.currentPageIndex).toBe(2);
    sut.dispose();
  });

  it("moveToNextPage advances index", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2);
    sut.moveToNextPage();
    expect(sut.currentPageIndex).toBe(1);
    sut.dispose();
  });

  it("moveToPreviousPage decrements index", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2);
    sut.moveToLastPage();
    sut.moveToPreviousPage();
    expect(sut.currentPageIndex).toBe(1);
    sut.dispose();
  });
});

// ── pageSize mutation re-clamps currentPageIndex ──────────────────────────────

describe("PagedComposition – pageSize re-clamps", () => {
  it("re-clamps currentPageIndex when pageSize is set to a larger value", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 10; i++) source.push(i);
    const sut = new PagedComposition(source, 2); // pageCount=5
    sut.currentPageIndex = 4;
    sut.pageSize = 5; // pageCount = 2; index 4 > max(1) → clamp to 1
    expect(sut.currentPageIndex).toBe(1);
    sut.dispose();
  });
});

// ── propertyChanged observable ────────────────────────────────────────────────

describe("PagedComposition – propertyChanged", () => {
  it("fires on navigation", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 6; i++) source.push(i);
    const sut = new PagedComposition(source, 2);

    const changed: string[] = [];
    sut.propertyChanged.subscribe((name) => changed.push(name));

    sut.moveToNextPage();

    expect(changed).toContain("currentPageIndex");
    expect(changed).toContain("items");
    sut.dispose();
  });

  it("fires on source mutation", () => {
    const source = new ObservableList<number>();
    for (let i = 0; i < 3; i++) source.push(i);
    const sut = new PagedComposition(source, 2);

    const changed: string[] = [];
    sut.propertyChanged.subscribe((name) => changed.push(name));

    source.push(99); // triggers #onSourceMutated

    expect(changed).toContain("pageCount");
    sut.dispose();
  });
});

// ── source property ───────────────────────────────────────────────────────────

describe("PagedComposition – source property", () => {
  it("returns the original source", () => {
    const source = new ObservableList<number>();
    const sut = new PagedComposition(source, 2);
    expect(sut.source).toBe(source);
    sut.dispose();
  });

  it("preserves a factory function as source", () => {
    const items = [1, 2, 3];
    const factory = () => items;
    const sut = new PagedComposition(factory, 2);
    expect(sut.source).toBe(factory);
    sut.dispose();
  });
});

// ── dispose ───────────────────────────────────────────────────────────────────

describe("PagedComposition – dispose", () => {
  it("is idempotent", () => {
    const source = new ObservableList<number>();
    source.push(1);
    const sut = new PagedComposition(source, 1);
    expect(() => {
      sut.dispose();
      sut.dispose();
    }).not.toThrow();
  });
});
