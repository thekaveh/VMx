import { describe, expect, it } from "vitest";
import { ObservableList } from "../../../src/collections/observableList.js";
import { CollectionChangedMessage } from "../../../src/messages/collectionChanged.js";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import {
  RecordingMessageHub,
  recordCollectionChanges,
  recordObservableList,
  recordPropertyChanges,
} from "../../../src/testing/index.js";

describe("semantic message recorders", () => {
  it("filters property changes by sender and property name in delivery order", () => {
    const hub = new RecordingMessageHub();
    const sender = {};
    const other = {};
    const recorder = recordPropertyChanges(hub, { sender, propertyName: "name" });
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "name") {
        hub.send(PropertyChangedMessage.create(sender, "VM", "derived"));
      }
    });

    hub.send(PropertyChangedMessage.create(other, "Other", "name"));
    hub.send(PropertyChangedMessage.create(sender, "VM", "ignored"));
    hub.send(PropertyChangedMessage.create(sender, "VM", "name"));

    expect(recorder.propertyNames).toEqual(["name"]);
    expect(recorder.records[0]?.sender).toBe(sender);
    const snapshot = recorder.records;
    recorder.clear();
    expect(recorder.records).toEqual([]);
    expect(snapshot).toHaveLength(1);
    recorder.dispose();
    recorder.dispose();
    hub.send(PropertyChangedMessage.create(sender, "VM", "name"));
    expect(recorder.records).toEqual([]);
    hub.dispose();
  });

  it("filters serviced collection messages by sender and action", () => {
    const hub = new RecordingMessageHub();
    const sender = {};
    const recorder = recordCollectionChanges<string>(hub, {
      sender,
      actions: ["add", "move"],
    });

    hub.batch(() => {
      hub.send(CollectionChangedMessage.forAdd(sender, "a", 0));
      hub.send(CollectionChangedMessage.forReplace(sender, "b", "a", 0));
      hub.send(CollectionChangedMessage.forMove(sender, "a", 0, 1));
      hub.send(CollectionChangedMessage.forAdd({}, "other", 0));
    });

    expect(recorder.actions).toEqual(["add", "move"]);
    expect(recorder.records.map((record) => record.newItems)).toEqual([["a"], ["a"]]);
    recorder.dispose();
    hub.dispose();
  });
});

describe("ObservableList recorder", () => {
  it("normalizes add, remove, replace, and reset without coupling to Subjects", () => {
    const list = new ObservableList<string>();
    const recorder = recordObservableList(list);

    list.push("a");
    list.replace(0, "b");
    list.removeAt(0);
    list.withBatch(() => {
      list.push("c");
      list.push("d");
    });

    expect(recorder.records).toEqual([
      { action: "add", newItems: ["a"], oldItems: [], newIndex: 0, oldIndex: -1 },
      { action: "replace", newItems: ["b"], oldItems: ["a"], newIndex: 0, oldIndex: 0 },
      { action: "remove", newItems: [], oldItems: ["b"], newIndex: -1, oldIndex: 0 },
      { action: "reset", newItems: [], oldItems: [], newIndex: -1, oldIndex: -1 },
    ]);

    const snapshot = recorder.records;
    recorder.clear();
    recorder.dispose();
    recorder.dispose();
    list.push("ignored");
    expect(recorder.records).toEqual([]);
    expect(snapshot).toHaveLength(4);
  });
});
