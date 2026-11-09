// Conformance tests: COL-067 — dictionary events and the hub message follow
// both key-view updates. A mutation changes the entries and size, then both
// key views, then raises the dictionary events and sends the hub message. The
// order of the two key-view notifications is not checked.
// See spec/21-collections.md §4.2 and ADR-0177 (#1176).

import { describe, expect, it } from "vitest";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import type { ObservableList } from "../../src/collections/observableList.js";
import { MessageHub } from "../../src/services/messageHub.js";

type Dictionary = ObservableDictionary<string, number, string>;

interface Snapshot {
  readonly entries: string;
  readonly size: number;
  readonly keys1: string;
  readonly keys2: string;
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

const mutations: ReadonlyArray<
  readonly [string, (dictionary: Dictionary) => void, Snapshot]
> = [
  ["add", (dictionary) => dictionary.add("c", 3, "three"), added],
  ["set insert", (dictionary) => dictionary.set("c", 3, "three"), added],
  [
    "delete",
    (dictionary) => void dictionary.delete("a", 1),
    { entries: "b2two", size: 1, keys1: "b", keys2: "2" },
  ],
  [
    "clear",
    (dictionary) => dictionary.clear(),
    { entries: "", size: 0, keys1: "", keys2: "" },
  ],
];

describe("COL-067", () => {
  for (const [name, act, expected] of mutations) {
    it(`dictionary ${name} raises its events and the hub message after both key views`, () => {
      const hub = new MessageHub();
      const dictionary: Dictionary = new ObservableDictionary<
        string,
        number,
        string
      >(hub);
      dictionary.add("a", 1, "one");
      dictionary.add("b", 2, "two");
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
      // Both key views notify first, in an unspecified order; then the
      // dictionary event, then the hub message.
      expect(
        seen
          .slice(0, 2)
          .map(([channel]) => channel)
          .sort(),
      ).toEqual(["keys1", "keys2"]);
      expect(seen.slice(2).map(([channel]) => channel)).toEqual([
        "dictionary",
        "hub",
      ]);
      // A key-view handler sees the updated entries, size and own view.
      for (const [channel, state] of seen.slice(0, 2)) {
        expect(state.entries).toBe(final.entries);
        expect(state.size).toBe(final.size);
        if (channel === "keys1") expect(state.keys1).toBe(final.keys1);
        else expect(state.keys2).toBe(final.keys2);
      }
      // The dictionary event and the hub message see both views updated.
      for (const [, state] of seen.slice(2)) expect(state).toEqual(final);
    });
  }
});
