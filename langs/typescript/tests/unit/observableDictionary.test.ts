// Unit tests for ObservableDictionary<TKey1, TKey2, TValue>.
// Conformance-level tests live in tests/conformance/.

import { describe, expect, it } from "vitest";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

// ── Basic CRUD — no subscribers ───────────────────────────────────────────────

describe("ObservableDictionary basic CRUD", () => {
  it("set increments size", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("b", 2, 2.0);
    expect(sut.size).toBe(2);
  });

  it("set on existing key pair triggers replace, not add", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    const added: string[] = [];
    const replaced: string[] = [];
    sut.itemAdded.subscribe(() => added.push("added"));
    sut.itemReplaced.subscribe(() => replaced.push("replaced"));

    sut.set("a", 1, 9.9);

    expect(added).toHaveLength(0);
    expect(replaced).toHaveLength(1);
    expect(sut.get("a", 1)).toBeCloseTo(9.9);
    expect(sut.size).toBe(1);
  });

  it("delete returns true and decrements size", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    expect(sut.delete("a", 1)).toBe(true);
    expect(sut.size).toBe(0);
  });

  it("delete returns false for absent entry", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(sut.delete("x", 99)).toBe(false);
  });

  it("has returns true after set, false after delete", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    expect(sut.has("a", 1)).toBe(true);
    sut.delete("a", 1);
    expect(sut.has("a", 1)).toBe(false);
  });

  it("get returns undefined when absent", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(sut.get("missing", 99)).toBeUndefined();
  });

  it("clear empties dictionary and key views", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("b", 2, 2.0);
    sut.clear();
    expect(sut.size).toBe(0);
    expect(sut.keys1.length).toBe(0);
    expect(sut.keys2.length).toBe(0);
  });
});

// ── Null-key guard ────────────────────────────────────────────────────────────

describe("ObservableDictionary null-key guard", () => {
  it("set throws Error for null key1", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(() => sut.set(null as unknown as string, 1, 0)).toThrow();
  });

  it("set throws Error for null key2", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(() => sut.set("a", null as unknown as number, 0)).toThrow();
  });
});

// ── Distinct-key views ────────────────────────────────────────────────────────

describe("ObservableDictionary distinct-key views", () => {
  it("keys1 contains only distinct Key1 values", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("a", 2, 2.0);
    sut.set("b", 3, 3.0);
    expect(sut.keys1.length).toBe(2);
    expect([...sut.keys1]).toContain("a");
    expect([...sut.keys1]).toContain("b");
  });

  it("keys2 contains only distinct Key2 values", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("b", 1, 2.0);
    sut.set("c", 2, 3.0);
    expect(sut.keys2.length).toBe(2);
    expect([...sut.keys2]).toContain(1);
    expect([...sut.keys2]).toContain(2);
  });

  it("keys1 drops key when last entry for that key is removed", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("a", 2, 2.0);
    sut.delete("a", 1);
    expect([...sut.keys1]).toContain("a"); // still has ("a", 2)
    sut.delete("a", 2);
    expect([...sut.keys1]).not.toContain("a");
  });

  it("keys1 insertion order is preserved", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("c", 1, 1.0);
    sut.set("a", 2, 2.0);
    sut.set("b", 3, 3.0);
    expect([...sut.keys1]).toEqual(["c", "a", "b"]);
  });
});

// ── Events ────────────────────────────────────────────────────────────────────

describe("ObservableDictionary events", () => {
  it("itemAdded fires on set (new key pair) with correct payload", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const events: Array<{ key1: string; key2: number; value: number }> = [];
    sut.itemAdded.subscribe((e) =>
      events.push({
        key1: e.key1,
        key2: e.key2,
        value: e.value,
      }),
    );

    sut.set("a", 1, 7.7);

    expect(events).toHaveLength(1);
    expect(events[0]!.key1).toBe("a");
    expect(events[0]!.key2).toBe(1);
    expect(events[0]!.value).toBeCloseTo(7.7);
  });

  it("itemRemoved fires on delete with correct payload", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 7.7);
    const events: Array<{ key1: string; key2: number; value: number }> = [];
    sut.itemRemoved.subscribe((e) =>
      events.push({
        key1: e.key1,
        key2: e.key2,
        value: e.value,
      }),
    );

    sut.delete("a", 1);

    expect(events).toHaveLength(1);
    expect(events[0]!.key1).toBe("a");
    expect(events[0]!.key2).toBe(1);
    expect(events[0]!.value).toBeCloseTo(7.7);
  });

  it("itemReplaced fires on set (existing key pair) with old and new values", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    const events: Array<{ nv: number; ov: number }> = [];
    sut.itemReplaced.subscribe((e) =>
      events.push({ nv: e.newValue, ov: e.oldValue }),
    );

    sut.set("a", 1, 9.9);

    expect(events).toHaveLength(1);
    expect(events[0]!.nv).toBeCloseTo(9.9);
    expect(events[0]!.ov).toBeCloseTo(1.0);
  });

  it("reset fires on clear", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    const resets: boolean[] = [];
    sut.reset.subscribe(() => resets.push(true));

    sut.clear();

    expect(resets).toHaveLength(1);
  });
});

// ── Enumeration ───────────────────────────────────────────────────────────────

describe("ObservableDictionary enumeration", () => {
  it("iterates all entries in insertion order as [key1, key2, value] triples", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.1);
    sut.set("b", 2, 2.2);
    sut.set("c", 3, 3.3);

    const entries = [...sut];
    expect(entries).toHaveLength(3);
    expect(entries[0]![0]).toBe("a");
    expect(entries[0]![1]).toBe(1);
    expect(entries[0]![2]).toBeCloseTo(1.1);
    expect(entries[1]![0]).toBe("b");
    expect(entries[2]![0]).toBe("c");
  });

  it("yields no entries when empty", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect([...sut]).toHaveLength(0);
  });
});

// ── Edge cases ────────────────────────────────────────────────────────────────

describe("ObservableDictionary edge cases", () => {
  it("keys1 ObservableList fires itemAdded only on first appearance of Key1", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const added: string[] = [];
    sut.keys1.itemAdded.subscribe((e) => added.push(e.item));

    sut.set("x", 1, 1.0);
    sut.set("x", 2, 2.0); // same Key1 — no new event

    expect(added).toEqual(["x"]);
  });

  it("keys2 ObservableList fires itemRemoved when last entry for Key2 is removed", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 5, 1.0);
    const removed: number[] = [];
    sut.keys2.itemRemoved.subscribe((e) => removed.push(e.item));

    sut.delete("a", 5);

    expect(removed).toEqual([5]);
  });

  it("clear does not fire per-entry itemRemoved events", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 1.0);
    sut.set("b", 2, 2.0);
    sut.set("c", 3, 3.0);
    const fired: string[] = [];
    sut.itemRemoved.subscribe(() => fired.push("removed"));

    sut.clear();

    expect(fired).toHaveLength(0); // Clear must NOT fire per-entry events
  });

  it("delete of absent entry returns false without firing events", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const events: string[] = [];
    sut.itemRemoved.subscribe(() => events.push("removed"));

    const result = sut.delete("no", 99);

    expect(result).toBe(false);
    expect(events).toHaveLength(0);
  });
});

// ── tryGetValue ───────────────────────────────────────────────────────────────

describe("ObservableDictionary tryGetValue", () => {
  it("returns found=true and value when present", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("a", 1, 42.0);
    const result = sut.tryGetValue("a", 1);
    expect(result.found).toBe(true);
    expect(result.value).toBeCloseTo(42.0);
  });

  it("returns found=false and value=undefined when absent", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const result = sut.tryGetValue("missing", 99);
    expect(result.found).toBe(false);
    expect(result.value).toBeUndefined();
  });

  it("throws when key1 is null", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const badKey1: string = null as unknown as string;
    expect(() => sut.tryGetValue(badKey1, 1)).toThrow();
  });

  it("throws when key2 is undefined", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const badKey2: number = undefined as unknown as number;
    expect(() => sut.tryGetValue("a", badKey2)).toThrow();
  });
});

// ── Strict add ───────────────────────────────────────────────────────────────

describe("ObservableDictionary strict add()", () => {
  it("add inserts a new entry and increments size", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.add("a", 1, 1.0);
    expect(sut.size).toBe(1);
    expect(sut.get("a", 1)).toBeCloseTo(1.0);
  });

  it("add fires itemAdded with correct payload", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const events: Array<{ key1: string; key2: number; value: number }> = [];
    sut.itemAdded.subscribe((e) =>
      events.push({ key1: e.key1, key2: e.key2, value: e.value }),
    );

    sut.add("x", 5, 42.0);

    expect(events).toHaveLength(1);
    expect(events[0]!.key1).toBe("x");
    expect(events[0]!.key2).toBe(5);
    expect(events[0]!.value).toBeCloseTo(42.0);
  });

  it("add throws when the key pair already exists", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.add("a", 1, 1.0);
    expect(() => sut.add("a", 1, 2.0)).toThrow();
  });

  it("add throws for null key1", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(() =>
      sut.add(null as unknown as string, 1, 0.0),
    ).toThrow();
  });

  it("add throws for null key2", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(() =>
      sut.add("a", null as unknown as number, 0.0),
    ).toThrow();
  });

  it("add does not replace: size remains 1 on duplicate-key attempt", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.add("a", 1, 1.0);
    expect(() => sut.add("a", 1, 2.0)).toThrow();
    // original value must be unchanged
    expect(sut.get("a", 1)).toBeCloseTo(1.0);
    expect(sut.size).toBe(1);
  });
});

// ── Hub injection ─────────────────────────────────────────────────────────────

describe("ObservableDictionary hub injection", () => {
  it("publishes add message on set (new key)", () => {
    const hub = new MessageHub();
    const sut = new ObservableDictionary<string, number, number>(hub);
    const received: CollectionChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof CollectionChangedMessage)
        received.push(m as CollectionChangedMessage<unknown>);
    });

    sut.set("a", 1, 42.0);

    expect(received).toHaveLength(1);
    expect(received[0]?.action).toBe("add");
    expect(received[0]?.senderObject).toBe(sut);
  });

  it("publishes replace message on set (existing key)", () => {
    const hub = new MessageHub();
    const sut = new ObservableDictionary<string, number, number>(hub);
    sut.set("a", 1, 1.0);
    const received: CollectionChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof CollectionChangedMessage)
        received.push(m as CollectionChangedMessage<unknown>);
    });

    sut.set("a", 1, 9.9);

    expect(received).toHaveLength(1);
    expect(received[0]?.action).toBe("replace");
  });

  it("publishes remove message on delete", () => {
    const hub = new MessageHub();
    const sut = new ObservableDictionary<string, number, number>(hub);
    sut.set("a", 1, 1.0);
    const received: CollectionChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof CollectionChangedMessage)
        received.push(m as CollectionChangedMessage<unknown>);
    });

    sut.delete("a", 1);

    expect(received).toHaveLength(1);
    expect(received[0]?.action).toBe("remove");
  });

  it("publishes reset message on clear", () => {
    const hub = new MessageHub();
    const sut = new ObservableDictionary<string, number, number>(hub);
    sut.set("a", 1, 1.0);
    const received: CollectionChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof CollectionChangedMessage)
        received.push(m as CollectionChangedMessage<unknown>);
    });

    sut.clear();

    expect(received).toHaveLength(1);
    expect(received[0]?.action).toBe("reset");
  });

  it("no hub: no errors on any mutation", () => {
    const sut = new ObservableDictionary<string, number, number>();
    expect(() => {
      sut.set("a", 1, 1.0);
      sut.set("a", 1, 2.0);
      sut.delete("a", 1);
      sut.set("b", 2, 3.0);
      sut.clear();
    }).not.toThrow();
  });
});
