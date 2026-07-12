// COL-048..055 — ServicedObservableCollection mutation parity.

import { describe, expect, it } from "vitest";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";

function observed<T>(...items: T[]): {
  readonly sut: ServicedObservableCollection<T>;
  readonly local: CollectionChangedMessage<T>[];
  readonly hubMessages: CollectionChangedMessage<T>[];
} {
  const hub = new MessageHub();
  const sut = new ServicedObservableCollection<T>(hub);
  items.forEach((item) => sut.push(item));
  const local: CollectionChangedMessage<T>[] = [];
  const hubMessages: CollectionChangedMessage<T>[] = [];
  sut.collectionChanged.subscribe((message) => local.push(message));
  hub.messages.subscribe((message) =>
    hubMessages.push(message as CollectionChangedMessage<T>),
  );
  return { sut, local, hubMessages };
}

describe("COL-048", () => {
  it("removes only the first duplicate and leaves a missing value silent", () => {
    const { sut, local, hubMessages } = observed("a", "b", "a");

    expect(sut.remove("a")).toBe(true);
    expect(sut.toArray()).toEqual(["b", "a"]);
    expect(local).toEqual([
      expect.objectContaining({
        action: "remove",
        oldItems: ["a"],
        newItems: [],
        index: 0,
        oldIndex: 0,
        newIndex: -1,
      }),
    ]);
    expect(hubMessages).toEqual(local);

    expect(sut.remove("missing")).toBe(false);
    expect(sut.toArray()).toEqual(["b", "a"]);
    expect(local).toHaveLength(1);
    expect(hubMessages).toHaveLength(1);
  });
});

describe("COL-049", () => {
  it("removes by strict index and rejects invalid indices atomically", () => {
    const { sut, local, hubMessages } = observed("a", "b", "c");

    expect(sut.removeAt(1)).toBeUndefined();
    expect(sut.toArray()).toEqual(["a", "c"]);
    expect(local).toEqual([
      expect.objectContaining({
        action: "remove",
        oldItems: ["b"],
        index: 1,
        oldIndex: 1,
        newIndex: -1,
      }),
    ]);
    expect(hubMessages).toEqual(local);

    for (const index of [-1, 2]) {
      expect(() => sut.removeAt(index)).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["a", "c"]);
      expect(local).toHaveLength(1);
      expect(hubMessages).toHaveLength(1);
    }
  });

  it.each([0.5, Number.NaN])(
    "rejects the non-integer index %s without mutation",
    (index) => {
      const { sut, local, hubMessages } = observed("a", "b", "c");

      expect(() => sut.removeAt(index)).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["a", "b", "c"]);
      expect(local).toEqual([]);
      expect(hubMessages).toEqual([]);
    },
  );
});

describe("COL-050", () => {
  it("replaces explicitly, including identical items, and validates first", () => {
    const { sut, local, hubMessages } = observed("a", "b");

    sut.replace(1, "c");
    sut.replace(1, "c");
    sut.setAt(0, "z");

    expect(sut.toArray()).toEqual(["z", "c"]);
    expect(local).toEqual([
      expect.objectContaining({
        action: "replace",
        oldItems: ["b"],
        newItems: ["c"],
        index: 1,
        oldIndex: 1,
        newIndex: 1,
      }),
      expect.objectContaining({
        action: "replace",
        oldItems: ["c"],
        newItems: ["c"],
        index: 1,
        oldIndex: 1,
        newIndex: 1,
      }),
      expect.objectContaining({
        action: "replace",
        oldItems: ["a"],
        newItems: ["z"],
        index: 0,
        oldIndex: 0,
        newIndex: 0,
      }),
    ]);
    expect(hubMessages).toEqual(local);

    for (const index of [-1, 2]) {
      expect(() => sut.replace(index, "x")).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["z", "c"]);
      expect(local).toHaveLength(3);
      expect(hubMessages).toHaveLength(3);
    }
  });

  it.each([0.5, Number.NaN])(
    "rejects the non-integer index %s without mutation",
    (index) => {
      const { sut, local, hubMessages } = observed("a", "b");

      expect(() => sut.replace(index, "c")).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["a", "b"]);
      expect(local).toEqual([]);
      expect(hubMessages).toEqual([]);
    },
  );
});

describe("COL-051", () => {
  it("snapshots self and live iterables, reports one Reset, and fails atomically", () => {
    const { sut, local, hubMessages } = observed(1, 2);

    sut.replaceAll(sut);
    expect(sut.toArray()).toEqual([1, 2]);

    function* liveView(): Generator<number> {
      for (const item of sut) yield item * 10;
    }
    sut.replaceAll(liveView());
    sut.replaceAll([10, 20]);

    expect(sut.toArray()).toEqual([10, 20]);
    expect(local).toHaveLength(3);
    for (const message of local) {
      expect(message).toEqual(
        expect.objectContaining({
          action: "reset",
          oldItems: [],
          newItems: [],
          index: -1,
          oldIndex: -1,
          newIndex: -1,
        }),
      );
    }
    expect(hubMessages).toEqual(local);

    function* failing(): Generator<number> {
      yield 99;
      throw new Error("iteration failed");
    }
    expect(() => sut.replaceAll(failing())).toThrow("iteration failed");
    expect(sut.toArray()).toEqual([10, 20]);
    expect(local).toHaveLength(3);
    expect(hubMessages).toHaveLength(3);

    const empty = observed<number>();
    empty.sut.replaceAll([]);
    expect(empty.local).toEqual([]);
    expect(empty.hubMessages).toEqual([]);
  });
});

describe("COL-052", () => {
  it("moves in both directions with identity and precise positions", () => {
    const a = { id: "a" };
    const b = { id: "b" };
    const c = { id: "c" };
    const forward = observed(a, b, c);

    forward.sut.move(0, 2);

    expect(forward.sut.toArray()).toEqual([b, c, a]);
    expect(forward.sut.at(2)).toBe(a);
    expect(forward.local).toEqual([
      expect.objectContaining({
        action: "move",
        oldItems: [a],
        newItems: [a],
        index: 2,
        oldIndex: 0,
        newIndex: 2,
      }),
    ]);
    expect(forward.hubMessages).toEqual(forward.local);

    const backward = observed(a, b, c);
    backward.sut.move(2, 0);
    expect(backward.sut.toArray()).toEqual([c, a, b]);
    expect(backward.sut.at(0)).toBe(c);
    expect(backward.local).toEqual([
      expect.objectContaining({
        action: "move",
        oldItems: [c],
        newItems: [c],
        index: 0,
        oldIndex: 2,
        newIndex: 0,
      }),
    ]);
    expect(backward.hubMessages).toEqual(backward.local);
  });
});

describe("COL-053", () => {
  it("makes equal indices silent and rejects every invalid move atomically", () => {
    const { sut, local, hubMessages } = observed("a", "b", "c");

    sut.move(1, 1);
    expect(sut.toArray()).toEqual(["a", "b", "c"]);
    expect(local).toEqual([]);
    expect(hubMessages).toEqual([]);

    const invalidMoves: Array<readonly [number, number]> = [
      [-1, 0],
      [0, -1],
      [3, 0],
      [0, 3],
    ];
    for (const [fromIndex, toIndex] of invalidMoves) {
      expect(() => sut.move(fromIndex, toIndex)).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["a", "b", "c"]);
      expect(local).toEqual([]);
      expect(hubMessages).toEqual([]);
    }
  });

  it.each([
    { fromIndex: 0.5, toIndex: 0 },
    { fromIndex: Number.NaN, toIndex: 0 },
    { fromIndex: 0, toIndex: 0.5 },
    { fromIndex: 0, toIndex: Number.NaN },
  ])(
    "rejects non-integer move positions ($fromIndex, $toIndex) atomically",
    ({ fromIndex, toIndex }) => {
      const { sut, local, hubMessages } = observed("a", "b", "c");

      expect(() => sut.move(fromIndex, toIndex)).toThrow(RangeError);
      expect(sut.toArray()).toEqual(["a", "b", "c"]);
      expect(local).toEqual([]);
      expect(hubMessages).toEqual([]);
    },
  );
});

describe("COL-054", () => {
  it("delivers every effective operation local-before-hub with final state", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<number>(hub);
    const deliveries: string[] = [];
    sut.collectionChanged.subscribe((message) =>
      deliveries.push(`local:${message.action}:${sut.toArray().join(",")}`),
    );
    hub.messages.subscribe((message) => {
      const changed = message as CollectionChangedMessage<number>;
      deliveries.push(`hub:${changed.action}:${sut.toArray().join(",")}`);
    });

    sut.push(1);
    sut.push(2);
    sut.remove(1);
    sut.replace(0, 3);
    sut.replaceAll([4, 5]);
    sut.move(0, 1);
    sut.clear();

    expect(deliveries).toEqual([
      "local:add:1",
      "hub:add:1",
      "local:add:1,2",
      "hub:add:1,2",
      "local:remove:2",
      "hub:remove:2",
      "local:replace:3",
      "hub:replace:3",
      "local:reset:4,5",
      "hub:reset:4,5",
      "local:move:5,4",
      "hub:move:5,4",
      "local:reset:",
      "hub:reset:",
    ]);
  });
});

describe("COL-055", () => {
  it("makes empty clear silent and never invokes item lifecycle sentinels", () => {
    const calls: string[] = [];
    const item = {
      construct: () => calls.push("construct"),
      destruct: () => calls.push("destruct"),
      dispose: () => calls.push("dispose"),
      parent: null as object | null,
    };
    const other = { ...item };
    const replacement = { ...item };
    const { sut, local, hubMessages } = observed<typeof item>();

    sut.clear();
    expect(local).toEqual([]);
    expect(hubMessages).toEqual([]);

    sut.push(item);
    sut.push(other);
    sut.move(0, 1);
    sut.replace(0, replacement);
    sut.remove(replacement);
    sut.push(replacement);
    sut.removeAt(0);
    sut.replaceAll([item, other]);
    sut.clear();

    expect(calls).toEqual([]);
    expect(item.parent).toBeNull();
    expect(other.parent).toBeNull();
    expect(replacement.parent).toBeNull();
    expect(local.at(-1)).toEqual(
      expect.objectContaining({
        action: "reset",
        oldItems: [],
        newItems: [],
        index: -1,
        oldIndex: -1,
        newIndex: -1,
      }),
    );
    expect(hubMessages).toEqual(local);
  });
});
