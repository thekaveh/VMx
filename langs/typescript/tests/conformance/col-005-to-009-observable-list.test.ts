// Conformance tests: COL-005..COL-009 — ObservableList<T> granular events.
// See spec/21-collections.md §3 and ADR-0026.

import { describe, it, expect } from "vitest";
import { ObservableList } from "../../src/collections/observableList.js";

describe("COL-005", () => {
  it("ObservableList ItemAdded emits (item, index) on Add", () => {
    const sut = new ObservableList<string>();
    sut.push("a"); // pre-populate so index is predictable

    const received: Array<{ item: string; index: number }> = [];
    sut.itemAdded.subscribe((e) => received.push(e));

    sut.push("b");

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe("b");
    expect(received[0]?.index).toBe(1);
  });
});

describe("COL-006", () => {
  it("ObservableList ItemRemoved emits (item, indexBeforeRemoval) on RemoveAt", () => {
    const sut = new ObservableList<string>();
    sut.push("x");
    sut.push("y");
    sut.push("z");

    const received: Array<{ item: string; index: number }> = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    sut.removeAt(1); // remove "y" at index 1

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe("y");
    expect(received[0]?.index).toBe(1); // index before removal
  });
});

describe("COL-007", () => {
  it("ObservableList ItemReplaced emits (newItem, oldItem, index) on Replace", () => {
    const sut = new ObservableList<string>();
    sut.push("old");
    sut.push("other");

    const received: Array<{ newItem: string; oldItem: string; index: number }> =
      [];
    sut.itemReplaced.subscribe((e) => received.push(e));

    sut.replace(0, "new");

    expect(received).toHaveLength(1);
    expect(received[0]?.newItem).toBe("new");
    expect(received[0]?.oldItem).toBe("old");
    expect(received[0]?.index).toBe(0);
  });
});

describe("COL-008", () => {
  it("ObservableList ItemAdded fires before PropertyChanged('Count') on every add", () => {
    const sut = new ObservableList<number>();
    const callOrder: string[] = [];

    sut.itemAdded.subscribe(() => callOrder.push("item_added"));
    sut.propertyChanged.subscribe((name) =>
      callOrder.push(`property_changed:${name}`),
    );

    sut.push(42);

    expect(callOrder).toEqual(["item_added", "property_changed:Count"]);
  });
});

describe("COL-009", () => {
  it("Inside batchUpdate only a single Reset fires; granular events are suppressed", () => {
    const sut = new ObservableList<number>();

    const granularEvents: string[] = [];
    const resets: null[] = [];

    sut.itemAdded.subscribe(() => granularEvents.push("added"));
    sut.itemRemoved.subscribe(() => granularEvents.push("removed"));
    sut.itemReplaced.subscribe(() => granularEvents.push("replaced"));
    sut.reset.subscribe(() => resets.push(null));

    sut.withBatch(() => {
      sut.push(1);
      sut.push(2);
      sut.removeAt(0);
      sut.replace(0, 99);
    });

    expect(granularEvents).toEqual([]);
    expect(resets).toHaveLength(1);
  });
});
