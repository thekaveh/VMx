// COL-040..047 — ObservableList replaceAll conformance.

import { describe, expect, it } from "vitest";
import { ObservableList } from "../../src/collections/observableList.js";

function observed(...items: number[]): [ObservableList<number>, string[]] {
  const sut = new ObservableList<number>();
  items.forEach((item) => sut.push(item));
  const events: string[] = [];
  sut.itemAdded.subscribe(() => events.push("add"));
  sut.itemRemoved.subscribe(() => events.push("remove"));
  sut.itemReplaced.subscribe(() => events.push("replace"));
  sut.reset.subscribe(() => events.push("reset"));
  sut.propertyChanged.subscribe((name) => events.push(`property:${name}`));
  return [sut, events];
}

describe("COL-040", () => {
  it("growth emits one Reset and Count", () => {
    const [sut, events] = observed(1);
    sut.replaceAll([2, 3, 4]);
    expect(sut.toArray()).toEqual([2, 3, 4]);
    expect(events).toEqual(["reset", "property:Count"]);
  });
});

describe("COL-041", () => {
  it("shrink emits one Reset and Count", () => {
    const [sut, events] = observed(1, 2, 3);
    sut.replaceAll([9]);
    expect(sut.toArray()).toEqual([9]);
    expect(events).toEqual(["reset", "property:Count"]);
  });
});

describe("COL-042", () => {
  it("equal count and identical non-empty contents emit Reset without Count", () => {
    const [sut, events] = observed(1, 2);
    sut.replaceAll([3, 4]);
    sut.replaceAll([3, 4]);
    expect(events).toEqual(["reset", "reset"]);
  });
});

describe("COL-043", () => {
  it("empty-to-empty is silent while non-empty-to-empty is effective", () => {
    const [empty, emptyEvents] = observed();
    empty.replaceAll([]);
    expect(emptyEvents).toEqual([]);
    const [sut, events] = observed(1);
    sut.replaceAll([]);
    expect(events).toEqual(["reset", "property:Count"]);
  });
});

describe("COL-044", () => {
  it("snapshots iterable input before mutation", () => {
    const [sut, events] = observed(1, 2, 3);
    sut.replaceAll(sut);
    expect(sut.toArray()).toEqual([1, 2, 3]);
    expect(events).toEqual(["reset"]);
  });
});

describe("COL-045", () => {
  it("nested replacement emits only the outermost Reset", () => {
    const [sut, events] = observed(1);
    sut.withBatch(() => {
      sut.replaceAll([2, 3]);
      expect(events).toEqual([]);
    });
    expect(events).toEqual(["reset", "property:Count"]);
  });
});

describe("COL-046", () => {
  it("exceptional batch exit restores scope and publishes the mutation", () => {
    const [sut, events] = observed(1);
    expect(() =>
      sut.withBatch(() => {
        sut.replaceAll([2, 3]);
        throw new Error("boom");
      }),
    ).toThrow("boom");
    expect(events).toEqual(["reset", "property:Count"]);
    sut.replaceAll([4, 5]);
    expect(events).toEqual(["reset", "property:Count", "reset"]);
  });
});

describe("COL-047", () => {
  it("Reset precedes Count and both observe final state", () => {
    const [sut] = observed(1);
    const observations: string[] = [];
    sut.reset.subscribe(() => observations.push(`reset:${sut.toArray().join(",")}`));
    sut.propertyChanged.subscribe((name) =>
      observations.push(`${name}:${sut.toArray().join(",")}`),
    );
    sut.replaceAll([7, 8]);
    expect(observations).toEqual(["reset:7,8", "Count:7,8"]);
  });
});

it("replaceAll snapshots a failing iterable atomically", () => {
  const [sut, events] = observed(1, 2);
  function* failing(): Generator<number> {
    yield 9;
    throw new Error("iteration failed");
  }
  expect(() => sut.replaceAll(failing())).toThrow("iteration failed");
  expect(sut.toArray()).toEqual([1, 2]);
  expect(events).toEqual([]);
});
