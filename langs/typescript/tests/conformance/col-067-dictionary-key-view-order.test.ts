// Conformance tests: COL-067 — dictionary events and the hub message follow
// the key-view updates. A mutation changes the entries and size, then each key
// view that changes, then raises the dictionary events and sends the hub
// message. A key view changes only when a distinct key first appears or last
// disappears, so a mutation can change both views, one view, or none. The
// order of two key-view notifications is not checked.
// See spec/21-collections.md §4.2 and ADR-0177 (#1176, #1429).

import { describe, expect, it } from "vitest";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import type { ObservableList } from "../../src/collections/observableList.js";
import { MessageHub } from "../../src/services/messageHub.js";

type Dictionary = ObservableDictionary<string, number, string>;
type View = "keys1" | "keys2";

interface Snapshot {
  readonly entries: string;
  readonly size: number;
  readonly keys1: string;
  readonly keys2: string;
}

interface Mutation {
  readonly name: string;
  /** Entries added after ("a", 1) and ("b", 2). */
  readonly extra: ReadonlyArray<readonly [string, number, string]>;
  readonly act: (dictionary: Dictionary) => void;
  /** The key views that the mutation changes. */
  readonly changed: readonly View[];
  readonly expected: Snapshot;
}

const read = (dictionary: Dictionary): Snapshot => ({
  entries: [...dictionary]
    .map(([k1, k2, value]) => `${k1}${k2}${value}`)
    .join(","),
  size: dictionary.size,
  keys1: dictionary.keys1.toArray().join(","),
  keys2: dictionary.keys2.toArray().join(","),
});

const added: Snapshot = {
  entries: "a1one,b2two,c3three",
  size: 3,
  keys1: "a,b,c",
  keys2: "1,2,3",
};

const both: readonly View[] = ["keys1", "keys2"];

const mutations: readonly Mutation[] = [
  {
    name: "add",
    extra: [],
    act: (dictionary) => dictionary.add("c", 3, "three"),
    changed: both,
    expected: added,
  },
  {
    name: "set insert",
    extra: [],
    act: (dictionary) => dictionary.set("c", 3, "three"),
    changed: both,
    expected: added,
  },
  {
    name: "delete",
    extra: [],
    act: (dictionary) => void dictionary.delete("a", 1),
    changed: both,
    expected: { entries: "b2two", size: 1, keys1: "b", keys2: "2" },
  },
  {
    name: "clear",
    extra: [],
    act: (dictionary) => dictionary.clear(),
    changed: both,
    expected: { entries: "", size: 0, keys1: "", keys2: "" },
  },
  {
    // Only a new keys2 value appears; "a" is already in keys1.
    name: "add of a new keys2 value only",
    extra: [],
    act: (dictionary) => dictionary.add("a", 3, "three"),
    changed: ["keys2"],
    expected: {
      entries: "a1one,b2two,a3three",
      size: 3,
      keys1: "a,b",
      keys2: "1,2,3",
    },
  },
  {
    // Only the keys2 value 1 disappears; ("a", 3) keeps "a" in keys1.
    name: "delete of the last keys2 value only",
    extra: [["a", 3, "three"]],
    act: (dictionary) => void dictionary.delete("a", 1),
    changed: ["keys2"],
    expected: { entries: "b2two,a3three", size: 2, keys1: "a,b", keys2: "2,3" },
  },
  {
    // Both keys already appear in other entries, so no key view changes.
    name: "add that changes no key view",
    extra: [],
    act: (dictionary) => dictionary.add("a", 2, "a-two"),
    changed: [],
    expected: {
      entries: "a1one,b2two,a2a-two",
      size: 3,
      keys1: "a,b",
      keys2: "1,2",
    },
  },
];

describe("COL-067", () => {
  for (const { name, extra, act, changed, expected } of mutations) {
    it(`dictionary ${name} raises its events and the hub message after the changed key views`, () => {
      const hub = new MessageHub();
      const dictionary: Dictionary = new ObservableDictionary<
        string,
        number,
        string
      >(hub);
      dictionary.add("a", 1, "one");
      dictionary.add("b", 2, "two");
      for (const [key1, key2, value] of extra)
        dictionary.add(key1, key2, value);
      const start = read(dictionary);
      const seen: Array<readonly [string, Snapshot]> = [];
      const record = (channel: string) => (): void => {
        seen.push([channel, read(dictionary)]);
      };
      hub.messages.subscribe(record("hub"));
      dictionary.itemAdded.subscribe(record("dictionary"));
      dictionary.itemRemoved.subscribe(record("dictionary"));
      dictionary.reset.subscribe(record("dictionary"));
      const watch = <T>(channel: string, view: ObservableList<T>): void => {
        view.itemAdded.subscribe(record(channel));
        view.itemRemoved.subscribe(record(channel));
        view.reset.subscribe(record(channel));
      };
      watch("keys1", dictionary.keys1);
      watch("keys2", dictionary.keys2);

      act(dictionary);

      const final = read(dictionary);
      expect(final).toEqual(expected);
      // A view that does not change keeps its start content.
      for (const view of both)
        if (!changed.includes(view)) expect(final[view]).toBe(start[view]);
      // Each changed key view notifies first, in an unspecified order; then
      // the dictionary event, then the hub message. An unchanged view stays
      // silent.
      const views = changed.length;
      expect(
        seen
          .slice(0, views)
          .map(([channel]) => channel)
          .sort(),
      ).toEqual([...changed].sort());
      expect(seen.slice(views).map(([channel]) => channel)).toEqual([
        "dictionary",
        "hub",
      ]);
      // A key-view handler sees the updated entries, size and own view.
      for (const [channel, state] of seen.slice(0, views)) {
        expect(state.entries).toBe(final.entries);
        expect(state.size).toBe(final.size);
        if (channel === "keys1") expect(state.keys1).toBe(final.keys1);
        else expect(state.keys2).toBe(final.keys2);
      }
      // The dictionary event and the hub message see both views updated.
      for (const [, state] of seen.slice(views)) expect(state).toEqual(final);
    });
  }
});
