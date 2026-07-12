import { describe, expect, it } from "vitest";
import { KeyedServicedObservableCollection } from "../../src/collections/keyedServicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";

interface Item {
  key: string;
  value?: number;
}

const keyed = () =>
  new KeyedServicedObservableCollection<string, Item>({
    keyOf: (candidate) => candidate.key,
    hub: null,
  });

describe("KeyedServicedObservableCollection bounds", () => {
  it.each([-1, 1, 0.5, Number.NaN])(
    "rejects invalid replacement index %s atomically",
    (index) => {
      const sut = keyed();
      const a = { key: "a" };
      sut.push(a);

      expect(() => sut.replace(index, { key: "x" })).toThrow(RangeError);
      expect(sut.toArray()).toEqual([a]);
      expect(sut.get("a")).toBe(a);
    },
  );

  it.each([
    [-1, 0],
    [0, -1],
    [2, 0],
    [0, 2],
    [0.5, 0],
    [0, Number.NaN],
  ])("rejects invalid move (%s, %s) atomically", (fromIndex, toIndex) => {
    const sut = keyed();
    sut.push({ key: "a" });
    sut.push({ key: "b" });

    expect(() => sut.move(fromIndex, toIndex)).toThrow(RangeError);
    expect(sut.toArray().map((candidate) => candidate.key)).toEqual(["a", "b"]);
  });
});

describe("KeyedServicedObservableCollection splice normalization", () => {
  it("uses native negative-start and omitted-deleteCount behavior", () => {
    const sut = keyed();
    const a = { key: "a" };
    const b = { key: "b" };
    const c = { key: "c" };
    sut.replaceAll([a, b, c]);
    const events: CollectionChangedMessage<Item>[] = [];
    sut.collectionChanged.subscribe((message) => events.push(message));

    expect(sut.splice(-2)).toEqual([b, c]);
    expect(sut.toArray()).toEqual([a]);
    expect(sut.has("b")).toBe(false);
    expect(sut.has("c")).toBe(false);
    expect(events).toEqual([expect.objectContaining({ action: "reset" })]);
  });

  it("emits the normalized index for exactly one removal", () => {
    const sut = keyed();
    const a = { key: "a" };
    const b = { key: "b" };
    sut.replaceAll([a, b]);
    const events: CollectionChangedMessage<Item>[] = [];
    sut.collectionChanged.subscribe((message) => events.push(message));

    expect(sut.splice(-1, 1)).toEqual([b]);
    expect(events).toEqual([
      expect.objectContaining({ action: "remove", index: 1, oldItems: [b] }),
    ]);
  });

  it("allows a removed captured key to be reused in the same atomic splice", () => {
    const sut = keyed();
    const oldB = { key: "b", value: 1 };
    const newB = { key: "b", value: 2 };
    sut.replaceAll([{ key: "a" }, oldB, { key: "c" }]);

    expect(sut.splice(1, 1, newB)).toEqual([oldB]);
    expect(sut.get("b")).toBe(newB);
  });
});

describe("KeyedServicedObservableCollection native Map keys", () => {
  it("supports object identity and SameValueZero keys", () => {
    const objectKey = {};
    const otherObject = {};
    const objectKeys = new KeyedServicedObservableCollection<object, { key: object }>({
      keyOf: (candidate) => candidate.key,
    });
    const stored = { key: objectKey };
    objectKeys.push(stored);
    expect(objectKeys.get(objectKey)).toBe(stored);
    expect(objectKeys.get(otherObject)).toBeUndefined();

    const numericKeys = new KeyedServicedObservableCollection<number, { key: number }>({
      keyOf: (candidate) => candidate.key,
    });
    const nan = { key: Number.NaN };
    numericKeys.push(nan);
    expect(numericKeys.get(Number.NaN)).toBe(nan);
    expect(() => numericKeys.push({ key: Number.NaN })).toThrow(Error);
  });
});
