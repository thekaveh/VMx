// Conformance tests: COMP-014..018 + GRP-007..010 — search / filter.
// See spec/06-composite-vm.md, spec/07-group-vm.md, ADR-0014.

import { describe, expect, it } from "vitest";

import { SearchableState } from "../../src/index.js";

function ciSubstr(item: string, term: string): boolean {
  if (term === "") return true;
  return item.toLowerCase().includes(term.toLowerCase());
}

describe("COMP-014", () => {
  it("defaults to empty search term; Filtered = all items", () => {
    const items = ["apple", "banana", "cherry"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    expect(s.searchTerm).toBe("");
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    expect(snap.at(-1)).toEqual(items);
  });
});

describe("COMP-015", () => {
  it("setting SearchTerm triggers recompute", () => {
    const items = ["apple", "banana", "cherry"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "an";
    expect(snap.at(-1)).toEqual(["banana"]);
  });
});

describe("COMP-016", () => {
  it("search() forces immediate recompute, bypassing debounce", () => {
    const items = ["one", "two"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: (i, t) => t === "" || i === t,
      debounceMs: 1000,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "two";
    s.search();
    expect(snap.at(-1)).toEqual(["two"]);
  });
});

describe("COMP-017", () => {
  it("user-supplied predicate", () => {
    const items = ["a", "bb", "ccc"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: (i, t) => i.length > t.length,
      debounceMs: 0,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "bb";
    s.search();
    expect(snap.at(-1)).toEqual(["ccc"]);
  });
});

describe("COMP-018", () => {
  it("Filtered recomputes when items source changes", () => {
    const items: string[] = ["one"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: () => true,
      debounceMs: 0,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    items.push("two");
    s.search();
    expect(snap.at(-1)).toEqual(["one", "two"]);
  });
});

describe("GRP-007", () => {
  it("defaults to empty search term (group context)", () => {
    const items = ["x", "y"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    expect(s.searchTerm).toBe("");
  });
});

describe("GRP-008", () => {
  it("setting SearchTerm triggers recompute (group context)", () => {
    const items = ["x", "yx", "z"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "x";
    expect(snap.at(-1)).toEqual(["x", "yx"]);
  });
});

describe("GRP-009", () => {
  it("search() forces immediate (group context)", () => {
    const items = ["a", "b"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: (i, t) => t === "" || i === t,
      debounceMs: 1000,
    });
    const snap: (readonly string[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "b";
    s.search();
    expect(snap.at(-1)).toEqual(["b"]);
  });
});

describe("GRP-010", () => {
  it("user-supplied predicate (group context)", () => {
    const items = [1, 2, 3, 4];
    const s = new SearchableState<number>({
      items: () => items,
      predicate: (i, t) => i > (Number(t) || 0),
      debounceMs: 0,
    });
    const snap: (readonly number[])[] = [];
    s.filtered.subscribe((v) => snap.push(v));
    s.searchTerm = "2";
    s.search();
    expect(snap.at(-1)).toEqual([3, 4]);
  });
});

// Dispose path — not a conformance ID, but a regression guard for the
// `#disposed` idempotence guard and the Subject completions in dispose().
describe("SearchableState.dispose", () => {
  it("is idempotent", () => {
    const items = ["a"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    expect(() => s.dispose()).not.toThrow();
    expect(() => s.dispose()).not.toThrow();
  });

  it("completes the filtered stream", () => {
    const items = ["a"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    let completed = false;
    s.filtered.subscribe({ complete: () => { completed = true; } });
    s.dispose();
    expect(completed).toBe(true);
  });
});

describe("SearchableState.searchTerm setter equality guard", () => {
  it("skips no-op re-set (regression guard for SearchTerm equality check)", () => {
    const items = ["apple", "banana"];
    const s = new SearchableState<string>({
      items: () => items,
      predicate: ciSubstr,
      debounceMs: 0,
    });
    const sink: string[][] = [];
    s.filtered.subscribe((v) => sink.push([...v]));
    const initial = sink.length;

    s.searchTerm = "appl";
    const afterFirst = sink.length;
    expect(afterFirst).toBeGreaterThan(initial);

    s.searchTerm = "appl"; // same value
    expect(sink.length).toBe(afterFirst);
  });
});
