// Conformance stubs: COL-010..COL-015 — ObservableDictionary (multi-key).
// See spec/21-collections.md §4 and ADR-0025.
// Implemented in Substage 1C.

import { describe, it } from "vitest";

describe("COL-010", () => {
  it.todo(
    "ObservableDictionary insert sets containsKey and indexer returns value",
  );
});

describe("COL-011", () => {
  it.todo(
    "ObservableDictionary remove clears the entry and decrements count",
  );
});

describe("COL-012", () => {
  it.todo(
    "Replacing an ObservableDictionary entry returns new value without changing count",
  );
});

describe("COL-013", () => {
  it.todo(
    "ObservableDictionary keys1 and keys2 observable views reflect distinct keys in sync",
  );
});

describe("COL-014", () => {
  it.todo(
    "Enumerating ObservableDictionary yields entries in insertion order",
  );
});

describe("COL-015", () => {
  it.todo(
    "ObservableDictionary clear() resets count to 0 and empties keys1 and keys2 views",
  );
});
