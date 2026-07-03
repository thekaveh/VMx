// Unit tests for ObservableList<T>.
// Conformance-level tests live in tests/conformance/col-005-to-009-observable-list.test.ts.

import { describe, it, expect } from "vitest";
import {
  ObservableList,
  type ItemAddedEvent,
  type ItemRemovedEvent,
  type ItemReplacedEvent,
} from "../../src/collections/observableList.js";

// ---------------------------------------------------------------------------
// Basic mutations — no subscribers
// ---------------------------------------------------------------------------

describe("ObservableList – basic mutations", () => {
  it("push increments length", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    sut.push(2);
    expect(sut.length).toBe(2);
  });

  it("insert places item at correct position", () => {
    const sut = new ObservableList<number>();
    sut.push(10);
    sut.push(30);
    sut.insert(1, 20);
    expect(sut.toArray()).toEqual([10, 20, 30]);
  });

  it("insert at length appends; out-of-bounds throws RangeError", () => {
    // splice would silently normalize/clamp a bad index while the emitted
    // payload carried the raw value — bounds must fail fast instead.
    const sut = new ObservableList<number>();
    sut.push(10);
    sut.insert(1, 20);
    expect(sut.toArray()).toEqual([10, 20]);
    expect(() => sut.insert(-1, 99)).toThrow(RangeError);
    expect(() => sut.insert(3, 99)).toThrow(RangeError);
    expect(sut.toArray()).toEqual([10, 20]);
  });

  it("pop removes and returns last item", () => {
    const sut = new ObservableList<string>();
    sut.push("a");
    sut.push("b");
    const val = sut.pop();
    expect(val).toBe("b");
    expect(sut.length).toBe(1);
  });

  it("pop on empty list returns undefined", () => {
    const sut = new ObservableList<number>();
    expect(sut.pop()).toBeUndefined();
  });

  it("removeAt removes correct item", () => {
    const sut = new ObservableList<number>();
    sut.push(10);
    sut.push(20);
    sut.push(30);
    sut.removeAt(1);
    expect(sut.toArray()).toEqual([10, 30]);
  });

  it("removeAt throws RangeError on negative and out-of-bounds indices", () => {
    const sut = new ObservableList<number>();
    expect(() => sut.removeAt(0)).toThrow(RangeError);
    sut.push(1);
    expect(() => sut.removeAt(-1)).toThrow(RangeError);
    expect(() => sut.removeAt(1)).toThrow(RangeError);
  });

  it("remove returns true when item found", () => {
    const sut = new ObservableList<string>();
    sut.push("a");
    expect(sut.remove("a")).toBe(true);
    expect(sut.length).toBe(0);
  });

  it("remove returns false when item not found", () => {
    const sut = new ObservableList<string>();
    expect(sut.remove("nonexistent")).toBe(false);
  });

  it("replace changes item in place", () => {
    const sut = new ObservableList<string>();
    sut.push("old");
    sut.replace(0, "new");
    expect(sut.at(0)).toBe("new");
    expect(sut.length).toBe(1);
  });

  it("replace throws RangeError on negative and out-of-bounds indices", () => {
    const sut = new ObservableList<string>();
    expect(() => sut.replace(0, "x")).toThrow(RangeError);
    sut.push("a");
    expect(() => sut.replace(-1, "x")).toThrow(RangeError);
    expect(() => sut.replace(1, "x")).toThrow(RangeError);
  });

  it("clear empties the list", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    sut.push(2);
    sut.clear();
    expect(sut.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// itemAdded observable
// ---------------------------------------------------------------------------

describe("ObservableList – itemAdded", () => {
  it("emits on push with correct item and index", () => {
    const sut = new ObservableList<string>();
    const received: ItemAddedEvent<string>[] = [];
    sut.itemAdded.subscribe((e) => received.push(e));

    sut.push("hello");

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe("hello");
    expect(received[0]?.index).toBe(0);
  });

  it("emits on insert with correct insertion index", () => {
    const sut = new ObservableList<number>();
    sut.push(10);
    sut.push(30);
    const received: ItemAddedEvent<number>[] = [];
    sut.itemAdded.subscribe((e) => received.push(e));

    sut.insert(1, 20);

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe(20);
    expect(received[0]?.index).toBe(1);
  });

  it("index increments correctly across multiple pushes", () => {
    const sut = new ObservableList<number>();
    const received: ItemAddedEvent<number>[] = [];
    sut.itemAdded.subscribe((e) => received.push(e));

    sut.push(1);
    sut.push(2);
    sut.push(3);

    expect(received).toHaveLength(3);
    expect(received[0]?.index).toBe(0);
    expect(received[1]?.index).toBe(1);
    expect(received[2]?.index).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// itemRemoved observable
// ---------------------------------------------------------------------------

describe("ObservableList – itemRemoved", () => {
  it("emits on pop with correct item and index", () => {
    const sut = new ObservableList<string>();
    sut.push("x");
    const received: ItemRemovedEvent<string>[] = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    sut.pop();

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe("x");
    expect(received[0]?.index).toBe(0);
  });

  it("emits on removeAt with index before removal", () => {
    const sut = new ObservableList<number>();
    sut.push(10);
    sut.push(20);
    sut.push(30);
    const received: ItemRemovedEvent<number>[] = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    sut.removeAt(1);

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe(20);
    expect(received[0]?.index).toBe(1);
  });

  it("emits on remove (by value) with index before removal", () => {
    const sut = new ObservableList<string>();
    sut.push("a");
    sut.push("b");
    sut.push("c");
    const received: ItemRemovedEvent<string>[] = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    sut.remove("b");

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe("b");
    expect(received[0]?.index).toBe(1);
  });

  it("does not emit when remove is called with missing item", () => {
    const sut = new ObservableList<string>();
    const received: ItemRemovedEvent<string>[] = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    const removed = sut.remove("nonexistent");

    expect(removed).toBe(false);
    expect(received).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// itemReplaced observable
// ---------------------------------------------------------------------------

describe("ObservableList – itemReplaced", () => {
  it("emits on replace with newItem, oldItem, and index", () => {
    const sut = new ObservableList<string>();
    sut.push("old");
    const received: ItemReplacedEvent<string>[] = [];
    sut.itemReplaced.subscribe((e) => received.push(e));

    sut.replace(0, "new");

    expect(received).toHaveLength(1);
    expect(received[0]?.newItem).toBe("new");
    expect(received[0]?.oldItem).toBe("old");
    expect(received[0]?.index).toBe(0);
  });

  it("does not emit propertyChanged Count on replace", () => {
    const sut = new ObservableList<string>();
    sut.push("a");
    const propEvents: string[] = [];
    sut.propertyChanged.subscribe((n) => propEvents.push(n));

    sut.replace(0, "b");

    expect(propEvents).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// reset observable
// ---------------------------------------------------------------------------

describe("ObservableList – reset", () => {
  it("emits on clear", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    let resetCount = 0;
    sut.reset.subscribe(() => resetCount++);

    sut.clear();

    expect(resetCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// propertyChanged ordering
// ---------------------------------------------------------------------------

describe("ObservableList – propertyChanged Count ordering", () => {
  it("Count fires after itemAdded on push", () => {
    const sut = new ObservableList<number>();
    const order: string[] = [];
    sut.itemAdded.subscribe(() => order.push("itemAdded"));
    sut.propertyChanged.subscribe((n) => order.push(`prop:${n}`));

    sut.push(1);

    expect(order).toEqual(["itemAdded", "prop:Count"]);
  });

  it("Count fires after itemRemoved on removeAt", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    const order: string[] = [];
    sut.itemRemoved.subscribe(() => order.push("itemRemoved"));
    sut.propertyChanged.subscribe((n) => order.push(`prop:${n}`));

    sut.removeAt(0);

    expect(order).toEqual(["itemRemoved", "prop:Count"]);
  });
});

// ---------------------------------------------------------------------------
// withBatch
// ---------------------------------------------------------------------------

describe("ObservableList – withBatch", () => {
  it("suppresses granular events and fires one reset", () => {
    const sut = new ObservableList<number>();
    const granular: string[] = [];
    let resetCount = 0;

    sut.itemAdded.subscribe(() => granular.push("added"));
    sut.itemRemoved.subscribe(() => granular.push("removed"));
    sut.itemReplaced.subscribe(() => granular.push("replaced"));
    sut.reset.subscribe(() => resetCount++);

    sut.withBatch(() => {
      sut.push(1);
      sut.push(2);
      sut.removeAt(0);
      sut.replace(0, 99);
    });

    expect(granular).toEqual([]);
    expect(resetCount).toBe(1);
  });

  it("fires no reset when no mutations occur in batch", () => {
    const sut = new ObservableList<number>();
    let resetCount = 0;
    sut.reset.subscribe(() => resetCount++);

    sut.withBatch(() => {
      // no mutations
    });

    expect(resetCount).toBe(0);
  });

  it("nested batch only fires reset on outermost exit", () => {
    const sut = new ObservableList<number>();
    const granular: string[] = [];
    let resetCount = 0;

    sut.itemAdded.subscribe(() => granular.push("added"));
    sut.reset.subscribe(() => resetCount++);

    sut.withBatch(() => {
      sut.push(1);
      sut.withBatch(() => {
        sut.push(2);
      });
      // inner batch exits — no reset yet
      expect(resetCount).toBe(0);
      expect(granular).toHaveLength(0);
    });

    expect(resetCount).toBe(1);
    expect(granular).toHaveLength(0);
  });

  it("normal events resume after batch exits", () => {
    const sut = new ObservableList<number>();
    const received: ItemAddedEvent<number>[] = [];
    sut.itemAdded.subscribe((e) => received.push(e));

    sut.withBatch(() => {
      sut.push(1);
    });

    // After batch, granular events resume
    sut.push(2);

    expect(received).toHaveLength(1);
    expect(received[0]?.item).toBe(2);
    expect(received[0]?.index).toBe(1);
  });

  it("fires reset even when callback throws", () => {
    const sut = new ObservableList<number>();
    let resetCount = 0;
    sut.reset.subscribe(() => resetCount++);

    expect(() =>
      sut.withBatch(() => {
        sut.push(1);
        throw new Error("test error");
      }),
    ).toThrow("test error");

    expect(resetCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("ObservableList – edge cases", () => {
  it("duplicate items: remove removes only first occurrence", () => {
    const sut = new ObservableList<string>();
    sut.push("dup");
    sut.push("dup");
    const received: ItemRemovedEvent<string>[] = [];
    sut.itemRemoved.subscribe((e) => received.push(e));

    sut.remove("dup");

    expect(sut.toArray()).toEqual(["dup"]);
    expect(received).toHaveLength(1);
    expect(received[0]?.index).toBe(0);
  });

  it("is iterable", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    sut.push(2);
    expect([...sut]).toEqual([1, 2]);
  });

  it("at() returns undefined for out-of-bounds", () => {
    const sut = new ObservableList<number>();
    expect(sut.at(0)).toBeUndefined();
  });

  it("toArray() returns a copy — mutation does not affect sut", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    const arr = sut.toArray();
    arr.push(99);
    expect(sut.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// withBatch Count notification (spec §3.3)
// ---------------------------------------------------------------------------

describe("ObservableList – withBatch Count notification", () => {
  it("emits propertyChanged('Count') when count grew during batch", () => {
    const sut = new ObservableList<number>();
    const propChanges: string[] = [];
    sut.propertyChanged.subscribe((n) => propChanges.push(n));

    sut.withBatch(() => {
      sut.push(1);
      sut.push(2);
    });

    expect(propChanges).toContain("Count");
  });

  it("emits propertyChanged('Count') when count shrank during batch", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    sut.push(2);
    sut.push(3);
    const propChanges: string[] = [];
    sut.propertyChanged.subscribe((n) => propChanges.push(n));

    sut.withBatch(() => {
      sut.removeAt(0);
      sut.removeAt(0);
    });

    expect(propChanges).toContain("Count");
  });

  it("does NOT emit propertyChanged('Count') when count is unchanged (replace-only batch)", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    sut.push(2);
    const propChanges: string[] = [];
    sut.propertyChanged.subscribe((n) => propChanges.push(n));

    sut.withBatch(() => {
      sut.replace(0, 10);
      sut.replace(1, 20);
    });

    expect(propChanges.filter((p) => p === "Count")).toHaveLength(0);
  });

  it("does NOT emit propertyChanged('Count') when add and remove net to zero", () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    const propChanges: string[] = [];
    sut.propertyChanged.subscribe((n) => propChanges.push(n));

    sut.withBatch(() => {
      sut.push(99);
      sut.removeAt(1); // net count change = 0
    });

    expect(propChanges.filter((p) => p === "Count")).toHaveLength(0);
  });

  it("emits propertyChanged('Count') on outermost batch exit for nested batches", () => {
    const sut = new ObservableList<number>();
    const propChanges: string[] = [];
    sut.propertyChanged.subscribe((n) => propChanges.push(n));

    sut.withBatch(() => {
      sut.withBatch(() => {
        sut.push(1);
      });
      // inner exited — no Count notification yet
      expect(propChanges.filter((p) => p === "Count")).toHaveLength(0);
    });

    // outermost exited — count changed (0 → 1), notification fires
    expect(propChanges).toContain("Count");
  });
});

// ---------------------------------------------------------------------------
// clear → Count (spec/21 §3.3, clarified by ADR-0037)
// ---------------------------------------------------------------------------

describe("ObservableList – clear emits Count", () => {
  it('fires propertyChanged("Count") after reset when count changed', () => {
    const sut = new ObservableList<number>();
    sut.push(1);
    const events: string[] = [];
    sut.reset.subscribe(() => events.push("reset"));
    sut.propertyChanged.subscribe((name) => events.push(name));

    sut.clear();

    expect(events).toEqual(["reset", "Count"]);
  });

  it("does not fire Count or Reset when clearing an empty list", () => {
    const sut = new ObservableList<number>();
    const events: string[] = [];
    let resetCount = 0;
    sut.propertyChanged.subscribe((name) => events.push(name));
    sut.reset.subscribe(() => resetCount++);

    sut.clear();

    // ADR-0037 §2.2: clearing an empty list changes nothing and emits nothing.
    expect(events).not.toContain("Count");
    expect(resetCount).toBe(0);
  });
});
