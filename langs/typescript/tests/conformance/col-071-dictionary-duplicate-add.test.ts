// Conformance tests: COL-071 — a duplicate dictionary add fails and changes
// nothing. `ObservableDictionary.add` of a key pair that is already present
// throws `Error`. The stored value, the entries, the key views and `size` do
// not change, and no local event or hub message is sent.
// See spec/21-collections.md §4.1 and ADR-0214 (#1308).

import { describe, expect, it } from "vitest";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import type { ReadOnlyObservableList } from "../../src/collections/readOnlyObservableList.js";
import { MessageHub } from "../../src/services/messageHub.js";

describe("COL-071", () => {
  it("a duplicate add throws Error and changes nothing", () => {
    const hub = new MessageHub();
    const dictionary = new ObservableDictionary<string, number, string>(hub);
    dictionary.add("a", 1, "one");
    dictionary.add("b", 2, "two");
    const events: string[] = [];
    hub.messages.subscribe(() => events.push("hub"));
    dictionary.itemAdded.subscribe(() => events.push("added"));
    dictionary.itemRemoved.subscribe(() => events.push("removed"));
    dictionary.itemReplaced.subscribe(() => events.push("replaced"));
    dictionary.reset.subscribe(() => events.push("reset"));
    const watch = <T>(channel: string, view: ReadOnlyObservableList<T>): void => {
      view.itemAdded.subscribe(() => events.push(channel));
      view.itemRemoved.subscribe(() => events.push(channel));
      view.reset.subscribe(() => events.push(channel));
    };
    watch("keys1", dictionary.keys1);
    watch("keys2", dictionary.keys2);

    let caught: unknown;
    try {
      dictionary.add("a", 1, "uno");
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).constructor).toBe(Error);
    expect(dictionary.get("a", 1)).toBe("one");
    expect(dictionary.size).toBe(2);
    expect([...dictionary].map(([k1, k2, value]) => `${k1}${k2}${value}`)).toEqual([
      "a1one",
      "b2two",
    ]);
    expect(dictionary.keys1.toArray()).toEqual(["a", "b"]);
    expect(dictionary.keys2.toArray()).toEqual([1, 2]);
    expect(events).toEqual([]);
  });
});
