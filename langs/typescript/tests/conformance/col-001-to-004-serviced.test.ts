// Conformance stubs: COL-001..COL-004 — ServicedObservableCollection<T>.
// See spec/21-collections.md §2 and ADR-0024.
// Implemented in Substage 1C.

import { describe, it } from "vitest";

describe("COL-001", () => {
  it.todo(
    "ServicedObservableCollection publishes to hub after local CollectionChanged on add",
  );
});

describe("COL-002", () => {
  it.todo(
    "ServicedObservableCollection publishes correct messages on remove and replace",
  );
});

describe("COL-003", () => {
  it.todo(
    "Null-hub fallback: no hub means no publication, no error on any mutation",
  );
});

describe("COL-004", () => {
  it.todo(
    "ServicedObservableCollection fires hub message on the caller thread without marshaling",
  );
});
