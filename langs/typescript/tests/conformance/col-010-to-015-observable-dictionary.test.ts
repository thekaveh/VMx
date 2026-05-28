// Conformance tests: COL-010..COL-015 — ObservableDictionary (multi-key).
// See spec/21-collections.md §4 and ADR-0025.

import { describe, expect, it } from "vitest";
import {
  type DictionaryItemAddedEvent,
  type DictionaryItemRemovedEvent,
  type DictionaryItemReplacedEvent,
  ObservableDictionary,
} from "../../src/collections/observableDictionary.js";

describe("COL-010", () => {
  it("ObservableDictionary insert sets has() and get() returns value", () => {
    const sut = new ObservableDictionary<string, number, number>();
    const added: DictionaryItemAddedEvent<string, number, number>[] = [];
    sut.itemAdded.subscribe((e) => added.push(e));

    sut.set("alpha", 1, 3.14);

    // has() is true after insert
    expect(sut.has("alpha", 1)).toBe(true);

    // get() returns correct value
    expect(sut.get("alpha", 1)).toBeCloseTo(3.14);

    // size incremented
    expect(sut.size).toBe(1);

    // itemAdded event fired with correct payload
    expect(added).toHaveLength(1);
    expect(added[0]!.key1).toBe("alpha");
    expect(added[0]!.key2).toBe(1);
    expect(added[0]!.value).toBeCloseTo(3.14);

    // keys1 contains new Key1
    const keys1 = [...sut.keys1];
    expect(keys1).toContain("alpha");

    // keys2 contains new Key2
    const keys2 = [...sut.keys2];
    expect(keys2).toContain(1);
  });
});

describe("COL-011", () => {
  it("ObservableDictionary remove clears the entry and fires itemRemoved", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("alpha", 1, 3.14);
    sut.set("alpha", 2, 2.72); // same key1, different key2
    sut.set("beta", 1, 1.41); // different key1, same key2

    const removed: DictionaryItemRemovedEvent<string, number, number>[] = [];
    sut.itemRemoved.subscribe((e) => removed.push(e));

    const result = sut.delete("alpha", 1);

    // Returns true
    expect(result).toBe(true);

    // Entry no longer present
    expect(sut.has("alpha", 1)).toBe(false);
    expect(sut.size).toBe(2);

    // itemRemoved fired with correct payload
    expect(removed).toHaveLength(1);
    expect(removed[0]!.key1).toBe("alpha");
    expect(removed[0]!.key2).toBe(1);
    expect(removed[0]!.value).toBeCloseTo(3.14);

    // "alpha" still in keys1 (because ("alpha",2) remains)
    expect([...sut.keys1]).toContain("alpha");

    // Key2=1 still in keys2 (because ("beta",1) remains)
    expect([...sut.keys2]).toContain(1);

    // Remove last entry using key2=2
    sut.delete("alpha", 2);
    expect([...sut.keys2]).not.toContain(2);

    // Remove last entry using key1="beta"
    sut.delete("beta", 1);
    expect([...sut.keys1]).not.toContain("beta");
    expect([...sut.keys2]).not.toContain(1);
  });
});

describe("COL-012", () => {
  it("Replacing an ObservableDictionary entry fires itemReplaced, not added/removed", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("alpha", 1, 3.14);

    const added: string[] = [];
    const removed: string[] = [];
    const replaced: DictionaryItemReplacedEvent<string, number, number>[] = [];

    sut.itemAdded.subscribe(() => added.push("added"));
    sut.itemRemoved.subscribe(() => removed.push("removed"));
    sut.itemReplaced.subscribe((e) => replaced.push(e));

    // Setting via set() on an existing key pair triggers replace
    sut.set("alpha", 1, 9.99);

    // New value is accessible
    expect(sut.get("alpha", 1)).toBeCloseTo(9.99);

    // Size unchanged
    expect(sut.size).toBe(1);

    // itemReplaced fired, NOT added or removed
    expect(added).toHaveLength(0); // Replace must NOT fire itemAdded
    expect(removed).toHaveLength(0); // Replace must NOT fire itemRemoved
    expect(replaced).toHaveLength(1);
    expect(replaced[0]!.key1).toBe("alpha");
    expect(replaced[0]!.key2).toBe(1);
    expect(replaced[0]!.newValue).toBeCloseTo(9.99);
    expect(replaced[0]!.oldValue).toBeCloseTo(3.14);
  });
});

describe("COL-013", () => {
  it("ObservableDictionary keys1 and keys2 observable views reflect distinct keys in sync", () => {
    const sut = new ObservableDictionary<string, number, number>();

    const keys1Added: string[] = [];
    const keys1Removed: string[] = [];
    sut.keys1.itemAdded.subscribe((e) => keys1Added.push(e.item));
    sut.keys1.itemRemoved.subscribe((e) =>
      keys1Removed.push(e.item),
    );

    const keys2Added: number[] = [];
    const keys2Removed: number[] = [];
    sut.keys2.itemAdded.subscribe((e) => keys2Added.push(e.item));
    sut.keys2.itemRemoved.subscribe((e) =>
      keys2Removed.push(e.item),
    );

    // First entry — both axes get new values
    sut.set("alpha", 1, 1.0);
    expect(keys1Added).toEqual(["alpha"]);
    expect(keys2Added).toEqual([1]);

    // Second entry with same Key1 — Keys1 must NOT fire again
    sut.set("alpha", 2, 2.0);
    expect(keys1Added).toHaveLength(1); // Key1='alpha' already present
    expect(keys2Added).toContain(2);

    // Entry with new Key1
    sut.set("beta", 1, 3.0);
    expect(keys1Added).toContain("beta");
    expect(keys2Added).toHaveLength(2); // Key2=1 already present

    // Remove ("alpha", 1) — "alpha" still alive via ("alpha", 2)
    sut.delete("alpha", 1);
    expect(keys1Removed).toHaveLength(0); // alpha still has entry

    // Remove ("alpha", 2) — "alpha" now gone
    sut.delete("alpha", 2);
    expect(keys1Removed).toContain("alpha");

    // Key2=2 disappeared when ("alpha",2) was removed
    expect(keys2Removed).toContain(2);
  });
});

describe("COL-014", () => {
  it("Enumerating ObservableDictionary yields entries in insertion order", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("alpha", 1, 1.1);
    sut.set("beta", 2, 2.2);
    sut.set("gamma", 1, 3.3);
    sut.set("alpha", 2, 4.4);

    const entries = [...sut];

    expect(entries).toHaveLength(4);
    expect(entries[0]![0]).toBe("alpha");
    expect(entries[0]![1]).toBe(1);
    expect(entries[0]![2]).toBeCloseTo(1.1);
    expect(entries[1]![0]).toBe("beta");
    expect(entries[1]![1]).toBe(2);
    expect(entries[1]![2]).toBeCloseTo(2.2);
    expect(entries[2]![0]).toBe("gamma");
    expect(entries[2]![1]).toBe(1);
    expect(entries[2]![2]).toBeCloseTo(3.3);
    expect(entries[3]![0]).toBe("alpha");
    expect(entries[3]![1]).toBe(2);
    expect(entries[3]![2]).toBeCloseTo(4.4);
  });
});

describe("COL-015", () => {
  it("ObservableDictionary clear() resets size to 0 and empties keys1 and keys2 views", () => {
    const sut = new ObservableDictionary<string, number, number>();
    sut.set("alpha", 1, 1.0);
    sut.set("beta", 2, 2.0);

    const granular: string[] = [];
    const resetFired: boolean[] = [];

    sut.itemAdded.subscribe(() => granular.push("added"));
    sut.itemRemoved.subscribe(() => granular.push("removed"));
    sut.reset.subscribe(() => resetFired.push(true));

    sut.clear();

    // Size drops to zero
    expect(sut.size).toBe(0);

    // keys1 and keys2 are empty
    expect(sut.keys1.length).toBe(0);
    expect(sut.keys2.length).toBe(0);

    // reset fired exactly once
    expect(resetFired).toHaveLength(1);

    // No individual itemAdded/Removed events fired during clear
    expect(granular).toHaveLength(0); // Clear must NOT fire per-entry events
  });
});

// ---------------------------------------------------------------------------
// COL-022 — ObservableDictionary hub publication (stub — implementation pending)
// ---------------------------------------------------------------------------

describe("COL-022", () => {
  it.todo(
    "ObservableDictionary hub publication — implementation pending (Substage 1C)",
  );
});
