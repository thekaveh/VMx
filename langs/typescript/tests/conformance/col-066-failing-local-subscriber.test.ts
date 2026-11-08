// Conformance tests: COL-066 — a failing local subscriber does not suppress
// the hub message. The change is committed and exactly one hub
// CollectionChangedMessage is sent. rxjs reports the subscriber error
// asynchronously and the mutation returns normally.
// See spec/01-concepts.md §1.4, spec/21-collections.md §2.5 and ADR-0171 (#1051).

import { config } from "rxjs";
import { describe, expect, it } from "vitest";
import { KeyedServicedObservableCollection } from "../../src/collections/keyedServicedObservableCollection.js";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

type ListLike =
  | ServicedObservableCollection<string>
  | KeyedServicedObservableCollection<string, string>;

const listMutations: ReadonlyArray<
  readonly [string, (list: ListLike) => void, string, readonly string[]]
> = [
  ["push", (list) => list.push("c"), "add", ["a", "b", "c"]],
  ["removeAt", (list) => list.removeAt(0), "remove", ["b"]],
  ["replace", (list) => list.replace(0, "z"), "replace", ["z", "b"]],
  ["move", (list) => list.move(0, 1), "move", ["b", "a"]],
  ["clear", (list) => list.clear(), "reset", []],
  ["replaceAll", (list) => list.replaceAll(["x", "y"]), "reset", ["x", "y"]],
];

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

describe("COL-066", () => {
  for (const kind of ["serviced", "keyed"] as const) {
    for (const [name, act, action, expected] of listMutations) {
      it(`${kind} ${name} sends one hub message despite a failing local subscriber`, async () => {
        const hub = new MessageHub();
        const list: ListLike =
          kind === "serviced"
            ? new ServicedObservableCollection<string>(hub)
            : new KeyedServicedObservableCollection<string, string>({
                keyOf: (item) => item,
                hub,
              });
        list.push("a");
        list.push("b");
        const order: string[] = [];
        const messages: CollectionChangedMessage<string>[] = [];
        hub.messages.subscribe((message) => {
          messages.push(message as CollectionChangedMessage<string>);
          order.push("hub");
        });
        list.collectionChanged.subscribe(() => {
          order.push("local");
          throw new Error("local subscriber failed");
        });

        const unhandled = await withUnhandledErrors(() => act(list));

        expect(list.toArray()).toEqual(expected);
        if (list instanceof KeyedServicedObservableCollection) {
          for (const item of expected) expect(list.get(item)).toBe(item);
        }
        expect(messages.map((message) => message.action)).toEqual([action]);
        expect(order).toEqual(["local", "hub"]);
        expect(unhandled).toHaveLength(1);
      });
    }
  }

  const dictionaryMutations: ReadonlyArray<
    readonly [
      string,
      (dictionary: ObservableDictionary<string, number, string>) => void,
      number,
    ]
  > = [
    ["add", (dictionary) => dictionary.add("b", 2, "two"), 2],
    ["delete", (dictionary) => void dictionary.delete("a", 1), 0],
    ["set", (dictionary) => dictionary.set("a", 1, "uno"), 1],
    ["clear", (dictionary) => dictionary.clear(), 0],
  ];

  for (const [name, act, size] of dictionaryMutations) {
    it(`dictionary ${name} sends one hub message despite a failing local subscriber`, async () => {
      const hub = new MessageHub();
      const dictionary = new ObservableDictionary<string, number, string>(hub);
      dictionary.add("a", 1, "one");
      const order: string[] = [];
      const messages: unknown[] = [];
      hub.messages.subscribe((message) => {
        messages.push(message);
        order.push("hub");
      });
      const fail = (): void => {
        order.push("local");
        throw new Error("local subscriber failed");
      };
      dictionary.itemAdded.subscribe(fail);
      dictionary.itemRemoved.subscribe(fail);
      dictionary.itemReplaced.subscribe(fail);
      dictionary.reset.subscribe(fail);

      const unhandled = await withUnhandledErrors(() => act(dictionary));

      expect(dictionary.size).toBe(size);
      if (name === "set") expect(dictionary.get("a", 1)).toBe("uno");
      expect(messages).toHaveLength(1);
      expect(messages[0]).toBeInstanceOf(CollectionChangedMessage);
      expect(order).toEqual(["local", "hub"]);
      expect(unhandled).toHaveLength(1);
    });
  }
});
