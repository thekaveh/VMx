// Conformance tests: COL-068 — dictionary Remove and Replace hub messages
// carry the entry's position in enumeration order.
// See spec/21-collections.md §4.7 and ADR-0193 (#1316).

import { describe, expect, it } from "vitest";
import {
  type DictionaryEntry,
  ObservableDictionary,
} from "../../src/collections/observableDictionary.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

type Entry = DictionaryEntry<string, number, string>;

function setUp(): {
  sut: ObservableDictionary<string, number, string>;
  messages: CollectionChangedMessage<Entry>[];
} {
  const hub = new MessageHub();
  const sut = new ObservableDictionary<string, number, string>(hub);
  sut.add("a", 1, "one");
  sut.add("b", 2, "two");
  sut.add("c", 3, "three");
  const messages: CollectionChangedMessage<Entry>[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof CollectionChangedMessage) {
      messages.push(message as CollectionChangedMessage<Entry>);
    }
  });
  return { sut, messages };
}

describe("COL-068", () => {
  it("Replace and Remove hub messages carry the entry position", () => {
    const { sut, messages } = setUp();

    sut.set("c", 3, "z");
    sut.delete("b", 2);

    expect(messages).toHaveLength(2);
    const [replace, remove] = messages;
    expect(replace?.action).toBe("replace");
    expect([replace?.index, replace?.oldIndex, replace?.newIndex]).toEqual([2, 2, 2]);
    expect(remove?.action).toBe("remove");
    expect([remove?.index, remove?.oldIndex, remove?.newIndex]).toEqual([1, 1, -1]);
  });
});

describe("ObservableDictionary Remove and Replace positions after local re-entry", () => {
  it("the Replace position is the entry's position when the message is sent", () => {
    const { sut, messages } = setUp();
    sut.itemReplaced.subscribe(() => {
      if (sut.has("a", 1)) sut.delete("a", 1);
    });

    sut.set("c", 3, "z");

    // "c" moved from 2 to 1 before the Replace message, as an Add reports (#733).
    const replace = messages.find((message) => message.action === "replace");
    expect([replace?.index, replace?.oldIndex, replace?.newIndex]).toEqual([1, 1, 1]);
  });

  it("the Replace position is -1 when a local subscriber removes the entry", () => {
    const { sut, messages } = setUp();
    sut.itemReplaced.subscribe(({ key1 }) => {
      if (key1 === "c") sut.delete("c", 3);
    });

    sut.set("c", 3, "z");

    expect(messages.map((m) => [m.action, m.index, m.oldIndex, m.newIndex])).toEqual([
      ["remove", 2, 2, -1],
      ["replace", -1, -1, -1],
    ]);
  });

  it("a local itemRemoved subscriber's removal does not change the Remove position", () => {
    const { sut, messages } = setUp();
    sut.itemRemoved.subscribe(({ key1 }) => {
      if (key1 === "c") sut.delete("a", 1);
    });

    sut.delete("c", 3);

    const remove = messages.find(
      (message) => message.action === "remove" && message.oldItems[0]?.key1 === "c",
    );
    expect([remove?.index, remove?.oldIndex, remove?.newIndex]).toEqual([2, 2, -1]);
  });
});
