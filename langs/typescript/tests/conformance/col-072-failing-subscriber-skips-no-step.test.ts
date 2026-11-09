// Conformance tests: COL-072 — a failing subscriber skips no later
// notification step of a committed change. ObservableList still emits "Count"
// after a failing granular or reset subscriber, and a failing key-view
// subscriber skips neither the dictionary's events nor its hub message. rxjs
// reports each subscriber error through onUnhandledError, and the mutation
// returns normally. See spec/21-collections.md §2.5, §3.3, §4.6 and ADR-0220
// (#1367, #1430).

import { config, type Observable } from "rxjs";
import { describe, expect, it } from "vitest";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import { ObservableList } from "../../src/collections/observableList.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

/** Runs `act` with rxjs unhandled-error reports recorded, then drains them. */
async function withUnhandledErrors(act: () => void): Promise<unknown[]> {
  const unhandled: unknown[] = [];
  const previous = config.onUnhandledError;
  config.onUnhandledError = (error) => unhandled.push(error);
  try {
    act();
    await new Promise((resolve) => setTimeout(resolve, 0));
  } finally {
    config.onUnhandledError = previous;
  }
  return unhandled;
}

function fail(): never {
  throw new Error("subscriber failed");
}

type List = ObservableList<number>;

const listCases: ReadonlyArray<
  readonly [string, number, (l: List) => Observable<unknown>, (l: List) => void, number]
> = [
  ["push", 0, (l) => l.itemAdded, (l) => l.push(1), 1],
  ["insert", 0, (l) => l.itemAdded, (l) => l.insert(0, 1), 1],
  ["remove", 1, (l) => l.itemRemoved, (l) => void l.remove(1), 0],
  ["removeAt", 1, (l) => l.itemRemoved, (l) => l.removeAt(0), 0],
  ["clear", 1, (l) => l.reset, (l) => l.clear(), 0],
  ["replaceAll", 1, (l) => l.reset, (l) => l.replaceAll([1, 2]), 2],
  ["withBatch", 0, (l) => l.reset, (l) => l.withBatch(() => l.push(1)), 1],
];

describe("COL-072", () => {
  for (const [name, initial, select, act, finalCount] of listCases) {
    it(`ObservableList ${name}: a failing subscriber skips neither the later subscriber nor Count`, async () => {
      const list: List = new ObservableList<number>();
      for (let n = 0; n < initial; n++) list.push(1);
      const names: string[] = [];
      list.propertyChanged.subscribe((property) => names.push(property));
      let later = 0;
      select(list).subscribe(fail);
      select(list).subscribe(() => later++);

      const unhandled = await withUnhandledErrors(() => {
        expect(() => act(list)).not.toThrow();
      });

      expect(list.length).toBe(finalCount);
      expect(later).toBe(1);
      expect(names).toEqual(["Count"]);
      expect(unhandled).toHaveLength(1);
    });
  }

  type Dictionary = ObservableDictionary<string, number, string>;
  const dictionaryCases: ReadonlyArray<
    readonly [string, (d: Dictionary) => Observable<unknown>, (d: Dictionary) => void]
  > = [
    ["add", (d) => d.itemAdded, (d) => d.add("b", 2, "x")],
    ["set", (d) => d.itemAdded, (d) => d.set("b", 2, "x")],
    ["delete", (d) => d.itemRemoved, (d) => void d.delete("a", 1)],
    ["clear", (d) => d.reset, (d) => d.clear()],
  ];

  for (const view of ["keys1", "keys2"] as const) {
    for (const [name, event, act] of dictionaryCases) {
      it(`dictionary ${name}: a failing ${view} subscriber skips no dictionary event or hub message`, async () => {
        const hub = new MessageHub();
        const dictionary: Dictionary = new ObservableDictionary<string, number, string>(hub);
        dictionary.add("a", 1, "v");
        const messages: unknown[] = [];
        hub.messages.subscribe((message) => {
          if (message instanceof CollectionChangedMessage) messages.push(message);
        });
        let events = 0;
        event(dictionary).subscribe(() => events++);
        const keyView = dictionary[view];
        const keyViewStreams: Observable<unknown>[] = [
          keyView.itemAdded,
          keyView.itemRemoved,
          keyView.reset,
        ];
        for (const stream of keyViewStreams) stream.subscribe(fail);

        const unhandled = await withUnhandledErrors(() => {
          expect(() => act(dictionary)).not.toThrow();
        });

        expect(events).toBe(1);
        expect(messages).toHaveLength(1);
        const entries = [...dictionary];
        expect(dictionary.keys1.toArray()).toEqual([...new Set(entries.map(([k1]) => k1))]);
        expect(dictionary.keys2.toArray()).toEqual([...new Set(entries.map(([, k2]) => k2))]);
        expect(unhandled).toHaveLength(1);
      });
    }
  }

  it("dictionary: after a failing keys2 subscriber on add, keys1 lists the new key", async () => {
    const dictionary: Dictionary = new ObservableDictionary<string, number, string>();
    const subscription = dictionary.keys2.itemAdded.subscribe(fail);

    const unhandled = await withUnhandledErrors(() => {
      expect(() => dictionary.add("a", 1, "v")).not.toThrow();
    });

    expect(dictionary.keys1.toArray()).toEqual(["a"]);
    expect(dictionary.keys2.toArray()).toEqual([1]);
    expect(unhandled).toHaveLength(1);
    subscription.unsubscribe();
    dictionary.add("a", 2, "z");
    expect(dictionary.keys1.toArray()).toEqual(["a"]);
    expect(dictionary.keys2.toArray()).toEqual([1, 2]);
    expect(dictionary.size).toBe(2);
  });
});
