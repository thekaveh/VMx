// Conformance tests: CAP-022 — IPageable capability contract surface.
// See spec/14-capabilities.md §2.10 and ADR-0023.

import { describe, expect, it } from "vitest";

import type { IPageable } from "../../src/capabilities/index.js";

// ---------------------------------------------------------------------------
// Minimal opt-in implementer (used only by CAP-022)
// ---------------------------------------------------------------------------

class PageableFixture implements IPageable {
  private _itemCount: number;
  private _pageSize: number;
  private _currentPageIndex: number;

  constructor(itemCount: number) {
    this._itemCount = itemCount;
    this._pageSize = 10;
    this._currentPageIndex = 0;
  }

  get pageSize(): number {
    return this._pageSize;
  }
  set pageSize(value: number) {
    this._pageSize = value < 0 ? 0 : value;
    this._currentPageIndex = this.clamp(this._currentPageIndex);
  }

  get currentPageIndex(): number {
    return this._currentPageIndex;
  }
  set currentPageIndex(value: number) {
    this._currentPageIndex = this.clamp(value);
  }

  get pageCount(): number {
    if (this._pageSize <= 0) return 1;
    return Math.ceil(this._itemCount / this._pageSize);
  }

  get isPagingEnabled(): boolean {
    return this._pageSize > 0;
  }

  moveToFirstPage(): void {
    this._currentPageIndex = 0;
  }

  moveToPreviousPage(): void {
    if (this._currentPageIndex > 0) this._currentPageIndex--;
  }

  moveToNextPage(): void {
    if (this._currentPageIndex < this.pageCount - 1) this._currentPageIndex++;
  }

  moveToLastPage(): void {
    this._currentPageIndex = this.pageCount - 1;
  }

  private clamp(index: number): number {
    if (this.pageCount === 0) return 0; // empty source: index stays at 0
    const max = this.pageCount - 1;
    if (index < 0) return 0;
    if (index > max) return max;
    return index;
  }
}

// ---------------------------------------------------------------------------
// CAP-022 — IPageable capability contract surface and clamping/navigation
// ---------------------------------------------------------------------------

describe("CAP-022", () => {
  it("IPageable contract: initial state, derived values correct", () => {
    const sut = new PageableFixture(25);
    expect(sut.pageSize).toBe(10);
    expect(sut.currentPageIndex).toBe(0);
    expect(sut.isPagingEnabled).toBe(true);
    expect(sut.pageCount).toBe(3); // ceil(25/10)
  });

  it("IPageable contract: pageSize=0 disables paging, pageCount=1, navigation no-ops", () => {
    const sut = new PageableFixture(25);
    sut.pageSize = 0;
    expect(sut.isPagingEnabled).toBe(false);
    expect(sut.pageCount).toBe(1);

    // Navigation while paging disabled — no-ops, index stays 0
    sut.moveToFirstPage();
    sut.moveToLastPage();
    expect(sut.currentPageIndex).toBe(0);
  });

  it("IPageable contract: clamping currentPageIndex above max and below 0", () => {
    const sut = new PageableFixture(25);
    sut.currentPageIndex = 99;
    expect(sut.currentPageIndex).toBe(2); // clamped to pageCount-1

    sut.currentPageIndex = -1;
    expect(sut.currentPageIndex).toBe(0); // clamped to 0
  });

  it("IPageable contract: navigation methods work and are no-ops at bounds", () => {
    const sut = new PageableFixture(25);

    sut.currentPageIndex = 1;
    sut.moveToFirstPage();
    expect(sut.currentPageIndex).toBe(0);

    sut.moveToLastPage();
    expect(sut.currentPageIndex).toBe(2);

    // moveToNextPage at upper bound is a no-op
    sut.moveToNextPage();
    expect(sut.currentPageIndex).toBe(2);

    // moveToPreviousPage decrements
    sut.moveToPreviousPage();
    expect(sut.currentPageIndex).toBe(1);

    // moveToPreviousPage at lower bound is a no-op
    sut.moveToFirstPage();
    sut.moveToPreviousPage();
    expect(sut.currentPageIndex).toBe(0);

    // moveToNextPage advances
    sut.moveToNextPage();
    expect(sut.currentPageIndex).toBe(1);
  });

  it("IPageable contract: pageSize resize clamps currentPageIndex", () => {
    const sut = new PageableFixture(25);
    sut.currentPageIndex = 2; // page 3 of 3
    sut.pageSize = 20; // now pageCount = ceil(25/20) = 2 → pages 0..1
    expect(sut.currentPageIndex).toBe(1); // clamped from 2 to 1
  });

  it("IPageable contract: itemCount=0 with pageSize>0 yields pageCount=0", () => {
    const empty = new PageableFixture(0);
    empty.pageSize = 5;
    expect(empty.pageCount).toBe(0); // ceil(0/5) = 0 (empty source has no pages)
  });
});
