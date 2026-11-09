// CollectionChangedMessage sender names (spec/21 §2.4, ADR-0194, #1309).
import { describe, expect, it } from "vitest";
import {
  CollectionChangedMessage,
  MessageHub,
  ObservableDictionary,
  ServicedObservableCollection,
} from "../../../src/index.js";

function record(hub: MessageHub): CollectionChangedMessage<unknown>[] {
  const messages: CollectionChangedMessage<unknown>[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof CollectionChangedMessage) messages.push(message);
  });
  return messages;
}

describe("CollectionChangedMessage sender name", () => {
  it("plain collections and dictionaries keep their type name", () => {
    const hub = new MessageHub();
    const messages = record(hub);
    const collection = new ServicedObservableCollection<number>(hub);
    const dictionary = new ObservableDictionary<string, number, string>(hub);

    collection.push(1);
    dictionary.add("a", 1, "one");

    expect(messages.map((message) => message.senderName)).toEqual([
      "ServicedObservableCollection",
      "ObservableDictionary",
    ]);
  });

  it("defaults to the sender's runtime type name and stores an explicit name", () => {
    const sender = new (class Owner {})();

    expect(CollectionChangedMessage.forReset(sender).senderName).toBe("Owner");
    expect(CollectionChangedMessage.forAdd(sender, 1, 0, "people").senderName).toBe("people");
    expect(CollectionChangedMessage.forRemove(sender, 1, 0, "people").senderName).toBe("people");
    expect(CollectionChangedMessage.forReplace(sender, 2, 1, 0, "people").senderName).toBe("people");
    expect(CollectionChangedMessage.forMove(sender, 1, 0, 1, "people").senderName).toBe("people");
    expect(CollectionChangedMessage.forReset(sender, "people").senderName).toBe("people");
  });
});
