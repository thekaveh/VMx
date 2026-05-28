// Conformance stubs: COL-005..COL-009 — ObservableList<T> granular events.
// See spec/21-collections.md §3 and ADR-0026.
// Implemented in Substage 1C.

import { describe, it } from "vitest";

describe("COL-005", () => {
  it.todo("ObservableList ItemAdded emits (item, index) on Add");
});

describe("COL-006", () => {
  it.todo(
    "ObservableList ItemRemoved emits (item, indexBeforeRemoval) on RemoveAt",
  );
});

describe("COL-007", () => {
  it.todo(
    "ObservableList ItemReplaced emits (newItem, oldItem, index) on Replace",
  );
});

describe("COL-008", () => {
  it.todo(
    "ObservableList ItemAdded fires before PropertyChanged('Count') on every add",
  );
});

describe("COL-009", () => {
  it.todo(
    "Inside batchUpdate only a single Reset fires; granular events are suppressed",
  );
});
