// #769: `Number.isInteger(-0)` is true and `-0 < 0` is false, so every index
// guard admits -0. Each emitted index must still be +0.

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  GroupVM,
  KeyedServicedObservableCollection,
  MessageHub,
  ObservableList,
  PagedComposition,
  RxDispatcher,
  ServicedObservableCollection,
} from "../../src/index.js";

type Indexed = { index?: number; newIndex?: number; oldIndex?: number };

/** Every index field that the payload carries, by name. */
function indices(payload: Indexed): Record<string, number> {
  const result: Record<string, number> = {};
  for (const field of ["index", "newIndex", "oldIndex"] as const) {
    const value = payload[field];
    if (value !== undefined) result[field] = value;
  }
  return result;
}

function expectNoNegativeZero(payloads: readonly Indexed[]): void {
  expect(payloads.length).toBeGreaterThan(0);
  for (const payload of payloads) {
    for (const [field, value] of Object.entries(indices(payload))) {
      expect(Object.is(value, -0), `${field} is -0`).toBe(false);
    }
  }
}

function hubPayloads(hub: MessageHub): Indexed[] {
  const payloads: Indexed[] = [];
  hub.messages.subscribe((message) => {
    if ("oldIndex" in message) payloads.push(message as Indexed);
  });
  return payloads;
}

function child(hub: MessageHub, name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build();
}

describe("#769 ObservableList emits +0 for a -0 index", () => {
  it("insert, removeAt and replace", () => {
    const sut = new ObservableList<string>();
    const payloads: Indexed[] = [];
    sut.itemAdded.subscribe((event) => payloads.push(event));
    sut.itemRemoved.subscribe((event) => payloads.push(event));
    sut.itemReplaced.subscribe((event) => payloads.push(event));

    sut.insert(-0, "a");
    sut.replace(-0, "b");
    sut.removeAt(-0);

    expect(payloads.map((payload) => Object.is(payload.index, 0))).toEqual([true, true, true]);
  });
});

describe.each([
  ["CompositeVM", (hub: MessageHub) =>
    CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, RxDispatcher.immediate())
      .children(() => [])
      .build()],
  ["GroupVM", (hub: MessageHub) =>
    GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, RxDispatcher.immediate())
      .children(() => [])
      .build()],
])("#769 %s emits +0 for a -0 index", (_name, build) => {
  it("insert, removeAt and setAt", () => {
    const hub = new MessageHub();
    const sut = build(hub);
    const local: Indexed[] = [];
    sut.collectionChanged.subscribe((event) => local.push(event));
    const published = hubPayloads(hub);

    sut.insert(-0, child(hub, "a"));
    sut.setAt(-0, child(hub, "b"));
    sut.removeAt(-0);

    expectNoNegativeZero(local);
    expectNoNegativeZero(published);
  });

  it("move with -0 as either index", () => {
    const hub = new MessageHub();
    const sut = build(hub);
    sut.add(child(hub, "a"));
    sut.add(child(hub, "b"));
    const local: Indexed[] = [];
    sut.collectionChanged.subscribe((event) => local.push(event));
    const published = hubPayloads(hub);

    sut.move(-0, 1);
    sut.move(1, -0);

    expect(local).toHaveLength(2);
    expectNoNegativeZero(local);
    expectNoNegativeZero(published);
  });
});

describe.each([
  ["ServicedObservableCollection", (hub: MessageHub) =>
    new ServicedObservableCollection<string>(hub)],
  ["KeyedServicedObservableCollection", (hub: MessageHub) =>
    new KeyedServicedObservableCollection<string, string>({ keyOf: (item) => item, hub })],
])("#769 %s emits +0 for a -0 index", (_name, build) => {
  it("removeAt, replace and move, locally and on the hub", () => {
    const hub = new MessageHub();
    const sut = build(hub);
    sut.push("a");
    sut.push("b");
    sut.push("c");
    const local: Indexed[] = [];
    sut.collectionChanged.subscribe((message) => local.push(message));
    const published = hubPayloads(hub);

    sut.replace(-0, "d");
    sut.move(-0, 2);
    sut.move(2, -0);
    sut.removeAt(-0);

    expect(local).toHaveLength(4);
    expectNoNegativeZero(local);
    expectNoNegativeZero(published);
    expect(published).toHaveLength(4);
  });
});

describe("#769 KeyedServicedObservableCollection stores +0 for a -0 index", () => {
  it("upsert and delete after replace(-0) with a new key", () => {
    const hub = new MessageHub();
    const sut = new KeyedServicedObservableCollection<string, string>({ keyOf: (item) => item, hub });
    sut.push("a");
    sut.push("b");
    sut.replace(-0, "z");
    const local: Indexed[] = [];
    sut.collectionChanged.subscribe((message) => local.push(message));

    sut.upsert("z");
    sut.delete("z");

    expect(local).toHaveLength(2);
    expectNoNegativeZero(local);
  });
});

describe("#769 PagedComposition stores +0 for a -0 page index", () => {
  it("currentPageIndex", () => {
    const sut = new PagedComposition(["a", "b", "c"], 1);
    sut.currentPageIndex = 2;

    sut.currentPageIndex = -0;

    expect(Object.is(sut.currentPageIndex, 0)).toBe(true);
  });
});
