// Conformance stubs: COL-016..COL-021 — PagedComposition<TVM>.
// See spec/21-collections.md §5 and ADR-0023.
// Implemented in Substage 1C.

import { describe, it } from "vitest";

describe("COL-016", () => {
  it.todo(
    "PagedComposition clamps currentPageIndex to [0, pageCount-1] when source shrinks",
  );
});

describe("COL-017", () => {
  it.todo(
    "PagedComposition pageCount equals ceil(sourceCount / pageSize) and updates on mutations",
  );
});

describe("COL-018", () => {
  it.todo(
    "PagedComposition moveToFirstPage / moveToLastPage are no-ops when already at bounds",
  );
});

describe("COL-019", () => {
  it.todo(
    "PagedComposition pageSize==0 disables paging and items yields the full source",
  );
});

describe("COL-020", () => {
  it.todo(
    "PagedComposition on empty source: pageCount==0, items empty, navigation is a no-op",
  );
});

describe("COL-021", () => {
  it.todo(
    "PagedComposition wrapping SearchableState filtered view pages the filtered count",
  );
});
