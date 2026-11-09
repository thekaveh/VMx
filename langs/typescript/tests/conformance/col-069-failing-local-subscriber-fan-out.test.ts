// Conformance tests: COL-069 — a failing local subscriber does not stop the
// later local subscribers. The failing subscriber stays attached, the hub gets
// one CollectionChangedMessage per change, and the mutation returns normally:
// rxjs reports each subscriber error through onUnhandledError.
// See spec/21-collections.md §2.5, spec/01-concepts.md §1.4,
// spec/03-messages.md §3.6 and ADR-0191 (#1311).

import { config, type Observable } from "rxjs";
import { describe, expect, it } from "vitest";
import { KeyedServicedObservableCollection } from "../../src/collections/keyedServicedObservableCollection.js";
import { ObservableDictionary } from "../../src/collections/observableDictionary.js";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
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

/** Two local subscribers, A then B; A fails on every delivery. */
function record(stream: Observable<unknown>): { a: unknown[]; b: unknown[] } {
  const seen = { a: [] as unknown[], b: [] as unknown[] };
  stream.subscribe((change) => {
    seen.a.push(change);
    throw new Error("local subscriber A failed");
  });
  stream.subscribe((change) => seen.b.push(change));
  return seen;
}

function hubMessages(hub: MessageHub): unknown[] {
  const messages: unknown[] = [];
  hub.messages.subscribe((message) => {
    expect(message).toBeInstanceOf(CollectionChangedMessage);
    messages.push(message);
  });
  return messages;
}

describe("COL-069", () => {
  for (const kind of ["serviced", "keyed"] as const) {
    it(`${kind}: a failing local subscriber does not stop the later subscriber`, async () => {
      const hub = new MessageHub();
      const list =
        kind === "serviced"
          ? new ServicedObservableCollection<string>(hub)
          : new KeyedServicedObservableCollection<string, string>({
              keyOf: (item) => item,
              hub,
            });
      const messages = hubMessages(hub);
      const seen = record(list.collectionChanged);

      const unhandled = await withUnhandledErrors(() => {
        expect(() => list.push("a")).not.toThrow();
        expect(() => list.push("b")).not.toThrow();
      });

      expect(list.toArray()).toEqual(["a", "b"]);
      expect(seen.b).toHaveLength(2);
      expect(seen.a).toEqual(seen.b);
      expect(
        messages.map((m) => (m as CollectionChangedMessage<string>).action),
      ).toEqual(["add", "add"]);
      expect(unhandled).toHaveLength(2);
    });
  }

  type Dictionary = ObservableDictionary<string, number, string>;
  const granular: ReadonlyArray<
    readonly [string, (d: Dictionary) => Observable<unknown>, (d: Dictionary, n: number) => void]
  > = [
    ["itemAdded", (d) => d.itemAdded, (d, n) => d.add(`k${String(n)}`, n, "v")],
    [
      "itemRemoved",
      (d) => d.itemRemoved,
      (d, n) => void d.delete(n === 0 ? "a" : "b", n + 1),
    ],
    ["itemReplaced", (d) => d.itemReplaced, (d, n) => d.set("a", 1, `r${String(n)}`)],
    ["reset", (d) => d.reset, (d) => d.clear()],
  ];

  for (const [event, select, act] of granular) {
    it(`dictionary ${event}: a failing handler does not stop the later handler`, async () => {
      const hub = new MessageHub();
      const dictionary: Dictionary = new ObservableDictionary<string, number, string>(hub);
      dictionary.add("a", 1, "one");
      dictionary.add("b", 2, "two");
      const seen = record(select(dictionary));
      const messages = hubMessages(hub);

      const unhandled = await withUnhandledErrors(() => {
        for (let n = 0; n < 2; n++) {
          if (event === "reset" && n === 1) {
            dictionary.add("c", 3, "three");
            messages.length = 0;
          }
          const before = messages.length;
          expect(() => act(dictionary, n)).not.toThrow();
          expect(messages).toHaveLength(before + 1);
        }
      });

      expect(seen.b).toHaveLength(2);
      expect(seen.a).toEqual(seen.b);
      expect(unhandled).toHaveLength(2);
    });
  }
});
