// COL-056..064 — KeyedServicedObservableCollection.

import { describe, expect, it } from "vitest";
import { KeyedServicedObservableCollection } from "../../src/collections/keyedServicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

interface Item {
  key: string;
  value: string;
  dispose?: () => void;
  destruct?: () => void;
  construct?: () => void;
  parent?: object | null;
}

function item(key: string, value = key): Item {
  return { key, value };
}

function observed(...items: Item[]): {
  readonly sut: KeyedServicedObservableCollection<string, Item>;
  readonly local: CollectionChangedMessage<Item>[];
  readonly hubMessages: CollectionChangedMessage<Item>[];
} {
  const hub = new MessageHub();
  const sut = new KeyedServicedObservableCollection<string, Item>({
    keyOf: (candidate) => candidate.key,
    hub,
  });
  items.forEach((candidate) => sut.push(candidate));
  const local: CollectionChangedMessage<Item>[] = [];
  const hubMessages: CollectionChangedMessage<Item>[] = [];
  sut.collectionChanged.subscribe((message) => local.push(message));
  hub.messages.subscribe((message) =>
    hubMessages.push(message as CollectionChangedMessage<Item>),
  );
  return { sut, local, hubMessages };
}

describe("COL-056", () => {
  it("uses captured keys for O(1)-expected lookup and preserves ordered reads", () => {
    let projections = 0;
    const a = item("a");
    const b = item("b");
    const c = item("c");
    const sut = new KeyedServicedObservableCollection<string, Item>({
      keyOf: (candidate) => {
        projections++;
        return candidate.key;
      },
    });
    [a, b, c].forEach((candidate) => sut.push(candidate));
    const events: CollectionChangedMessage<Item>[] = [];
    sut.collectionChanged.subscribe((message) => events.push(message));

    expect(sut.get("a")).toBe(a);
    expect(sut.get("b")).toBe(b);
    expect(sut.get("c")).toBe(c);
    expect(sut.has("a")).toBe(true);
    expect(sut.has("missing")).toBe(false);
    expect(sut.get("missing")).toBeUndefined();
    expect(projections).toBe(3);
    expect(sut.at(1)).toBe(b);
    expect([...sut]).toEqual([a, b, c]);
    expect(sut.toArray()).toEqual([a, b, c]);

    b.key = "renamed";
    expect(sut.get("b")).toBe(b);
    expect(sut.get("renamed")).toBeUndefined();
    expect(projections).toBe(3);
    expect(events).toEqual([]);
  });
});

describe("COL-057", () => {
  it("rejects duplicate and projector failures before changing state or channels", () => {
    const a = item("a");
    const b = item("b");
    const { sut, local, hubMessages } = observed(a, b);

    expect(() => sut.push(item("a", "duplicate"))).toThrow(Error);
    expect(() => sut.replace(0, item("b", "duplicate"))).toThrow(Error);
    expect(() => sut.replaceAll([item("x"), item("x")])).toThrow(Error);
    expect(() => sut.splice(0, 0, item("b", "duplicate"))).toThrow(Error);
    expect(sut.toArray()).toEqual([a, b]);
    expect(sut.get("a")).toBe(a);
    expect(sut.get("b")).toBe(b);
    expect(local).toEqual([]);
    expect(hubMessages).toEqual([]);

    const projectorError = new Error("projection failed");
    const failing = new KeyedServicedObservableCollection<string, Item>({
      keyOf: (candidate) => {
        if (candidate.key === "bad") throw projectorError;
        return candidate.key;
      },
    });
    failing.push(a);
    const failures: CollectionChangedMessage<Item>[] = [];
    failing.collectionChanged.subscribe((message) => failures.push(message));
    expect(() => failing.push(item("bad"))).toThrow(projectorError);
    expect(() => failing.replace(0, item("bad"))).toThrow(projectorError);
    expect(() => failing.replaceAll([item("ok"), item("bad")])).toThrow(
      projectorError,
    );
    expect(() => failing.upsert(item("bad"))).toThrow(projectorError);
    expect(() => failing.splice(0, 1, item("bad"))).toThrow(projectorError);
    expect(failing.toArray()).toEqual([a]);
    expect(failing.get("a")).toBe(a);
    expect(failures).toEqual([]);
  });
});

describe("COL-058", () => {
  it("upserts missing keys as Add and present keys as stable-position Replace", () => {
    const a = item("a");
    const b = item("b");
    const c = item("c");
    const b2 = item("b", "b2");
    const { sut, local, hubMessages } = observed(a, b);

    expect(sut.upsert(c)).toBe(true);
    expect(sut.upsert(b2)).toBe(false);
    expect(sut.upsert(b2)).toBe(false);

    expect(sut.toArray()).toEqual([a, b2, c]);
    expect(sut.get("b")).toBe(b2);
    expect(local).toEqual([
      expect.objectContaining({
        action: "add",
        newItems: [c],
        index: 2,
        oldIndex: -1,
        newIndex: 2,
      }),
      expect.objectContaining({
        action: "replace",
        oldItems: [b],
        newItems: [b2],
        index: 1,
        oldIndex: 1,
        newIndex: 1,
      }),
      expect.objectContaining({
        action: "replace",
        oldItems: [b2],
        newItems: [b2],
        index: 1,
      }),
    ]);
    expect(hubMessages).toEqual(local);
  });
});

describe("COL-059", () => {
  it("deletes by captured key with the pre-removal position and silent miss", () => {
    const a = item("a");
    const b = item("b");
    const c = item("c");
    const { sut, local, hubMessages } = observed(a, b, c);

    expect(sut.delete("b")).toBe(true);
    expect(sut.toArray()).toEqual([a, c]);
    expect(sut.get("b")).toBeUndefined();
    expect(sut.get("c")).toBe(c);
    expect(local).toEqual([
      expect.objectContaining({
        action: "remove",
        oldItems: [b],
        index: 1,
        oldIndex: 1,
        newIndex: -1,
      }),
    ]);
    expect(hubMessages).toEqual(local);

    expect(sut.delete("missing")).toBe(false);
    expect(local).toHaveLength(1);
    expect(hubMessages).toHaveLength(1);
  });
});

describe("COL-060", () => {
  it("keeps captured membership synchronized across removal and explicit rekey", () => {
    const a = item("a", "same");
    const equalA = item("a2", "same");
    const b = item("b");
    const c = item("c");
    const { sut } = observed(a, equalA, b, c);

    expect(sut.remove(a)).toBe(true);
    sut.removeAt(1);
    expect(sut.toArray()).toEqual([equalA, c]);
    expect(sut.get("a")).toBeUndefined();
    expect(sut.get("b")).toBeUndefined();
    expect(sut.get("a2")).toBe(equalA);
    expect(sut.get("c")).toBe(c);

    equalA.key = "rekeyed";
    sut.replace(0, equalA);
    expect(sut.get("a2")).toBeUndefined();
    expect(sut.get("rekeyed")).toBe(equalA);
    expect(() => sut.replace(0, item("c"))).toThrow(Error);
    expect(sut.get("rekeyed")).toBe(equalA);

    const same = item("old");
    const duplicated = observed(same).sut;
    same.key = "new";
    expect(duplicated.upsert(same)).toBe(true);
    expect(duplicated.toArray()).toEqual([same, same]);
    expect(duplicated.get("old")).toBe(same);
    expect(duplicated.get("new")).toBe(same);
  });
});

describe("COL-061", () => {
  it("preflights complete replacement, snapshots self, and keeps failures atomic", () => {
    const a = item("a");
    const b = item("b");
    const { sut, local, hubMessages } = observed(a, b);
    const x = item("x");
    const y = item("y");

    sut.replaceAll([x, y]);
    sut.replaceAll(sut);
    expect(sut.toArray()).toEqual([x, y]);
    expect(local.map((message) => message.action)).toEqual(["reset", "reset"]);
    expect(hubMessages).toEqual(local);

    function* failingInput(): Generator<Item> {
      yield item("z");
      throw new Error("iteration failed");
    }
    expect(() => sut.replaceAll([item("z"), item("z")])).toThrow(Error);
    expect(() => sut.replaceAll(failingInput())).toThrow("iteration failed");
    expect(sut.toArray()).toEqual([x, y]);
    expect(sut.get("x")).toBe(x);
    expect(sut.get("y")).toBe(y);
    expect(local).toHaveLength(2);
    expect(hubMessages).toHaveLength(2);

    const empty = observed().sut;
    const events: CollectionChangedMessage<Item>[] = [];
    empty.collectionChanged.subscribe((message) => events.push(message));
    empty.replaceAll([]);
    expect(events).toEqual([]);
  });
});

describe("COL-062", () => {
  it("validates splice final results and preserves ordinary messages and ownership", () => {
    const lifecycle: string[] = [];
    const a = {
      ...item("a"),
      construct: () => lifecycle.push("construct"),
      destruct: () => lifecycle.push("destruct"),
      dispose: () => lifecycle.push("dispose"),
      parent: null,
    };
    const b = item("b");
    const c = item("c");
    const replacement = item("b", "replacement");
    const { sut, local, hubMessages } = observed(a, b, c);

    expect(sut.splice(1, 1, replacement)).toEqual([b]);
    expect(sut.toArray()).toEqual([a, replacement, c]);
    expect(sut.get("b")).toBe(replacement);
    expect(local.at(-1)?.action).toBe("reset");

    const before = sut.toArray();
    expect(() => sut.splice(1, 0, item("a"))).toThrow(Error);
    expect(() => sut.splice(1, 1, item("c"), item("c"))).toThrow(Error);
    expect(sut.toArray()).toEqual(before);
    expect(local).toHaveLength(1);
    expect(hubMessages).toHaveLength(1);

    expect(sut.splice(1, 1)).toEqual([replacement]);
    expect(local.at(-1)).toEqual(
      expect.objectContaining({ action: "remove", index: 1 }),
    );
    expect(sut.get("b")).toBeUndefined();
    expect(sut.get("c")).toBe(c);

    sut.move(1, 0);
    expect(sut.toArray()).toEqual([c, a]);
    expect(sut.get("a")).toBe(a);
    expect(sut.get("c")).toBe(c);
    expect(sut.pop()).toBe(a);
    expect(sut.toArray()).toEqual([c]);
    expect(sut.splice(0, 0)).toEqual([]);
    sut.move(0, 0);
    sut.clear();
    sut.clear();
    expect(sut.length).toBe(0);
    expect(sut.has("c")).toBe(false);
    expect(lifecycle).toEqual([]);
    expect(a.parent).toBeNull();
    expect(hubMessages).toEqual(local);
  });
});

describe("COL-063", () => {
  it("commits state before local then hub delivery and defers hub transactions", () => {
    const hub = new MessageHub();
    const sut = new KeyedServicedObservableCollection<string, Item>({
      keyOf: (candidate) => candidate.key,
      hub,
    });
    const deliveries: string[] = [];
    sut.collectionChanged.subscribe((message) => {
      deliveries.push(
        `local:${message.action}:${sut.toArray().map((x) => x.key).join(",")}:${String(sut.has("a"))}`,
      );
    });
    hub.messages.subscribe((message) => {
      const changed = message as CollectionChangedMessage<Item>;
      deliveries.push(
        `hub:${changed.action}:${sut.toArray().map((x) => x.key).join(",")}:${String(sut.has("a"))}`,
      );
    });

    sut.push(item("a"));
    expect(deliveries).toEqual(["local:add:a:true", "hub:add:a:true"]);
    deliveries.length = 0;

    hub.batch(() => {
      sut.push(item("b"));
      sut.delete("a");
      expect(deliveries).toEqual([
        "local:add:a,b:true",
        "local:remove:b:false",
      ]);
    });
    expect(deliveries).toEqual([
      "local:add:a,b:true",
      "local:remove:b:false",
      "hub:add:b:false",
      "hub:remove:b:false",
    ]);
  });
});

describe("COL-064", () => {
  it("keeps lookup/index consistent through reentrant mutation and per-operation order", () => {
    const hub = new MessageHub();
    const sut = new KeyedServicedObservableCollection<string, Item>({
      keyOf: (candidate) => candidate.key,
      hub,
    });
    const order: string[] = [];
    let nested = false;
    sut.collectionChanged.subscribe((message) => {
      const key = message.newItems[0]?.key ?? message.oldItems[0]?.key ?? "reset";
      order.push(`local:${key}`);
      expect(sut.toArray().every((candidate) => sut.get(candidate.key) === candidate)).toBe(
        true,
      );
      if (!nested) {
        nested = true;
        sut.push(item("nested"));
      }
    });
    hub.messages.subscribe((message) => {
      const changed = message as CollectionChangedMessage<Item>;
      const key = changed.newItems[0]?.key ?? changed.oldItems[0]?.key ?? "reset";
      order.push(`hub:${key}`);
      expect(sut.get("outer")?.key).toBe("outer");
      expect(sut.get("nested")?.key).toBe("nested");
    });

    sut.push(item("outer"));

    expect(order.indexOf("local:outer")).toBeLessThan(order.indexOf("hub:outer"));
    expect(order.indexOf("local:nested")).toBeLessThan(order.indexOf("hub:nested"));
    expect(sut.toArray().map((candidate) => candidate.key)).toEqual([
      "outer",
      "nested",
    ]);
  });
});
