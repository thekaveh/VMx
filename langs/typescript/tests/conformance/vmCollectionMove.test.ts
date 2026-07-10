import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type {
  CollectionChangedEvent,
  ISelectableVmCollection,
  IVmCollection,
} from "../../src/index.js";

const dispatcher = RxDispatcher.immediate();

function child(hub: MessageHub, name: string, onConstruct?: () => void): ComponentVM {
  let builder = ComponentVM.builder().name(name).services(hub, dispatcher);
  if (onConstruct !== undefined) builder = builder.onConstruct(onConstruct);
  return builder.build();
}

function composite(hub: MessageHub, children: ComponentVM[] = [], autoConstruct = false) {
  return CompositeVM.builder<ComponentVM>()
    .name("composite")
    .services(hub, dispatcher)
    .children(() => children)
    .autoConstructOnAdd(autoConstruct)
    .build();
}

function group(hub: MessageHub, children: ComponentVM[] = []) {
  return GroupVM.builder<ComponentVM>()
    .name("group")
    .services(hub, dispatcher)
    .children(() => children)
    .build();
}

describe("COL-032", () => {
  it("exposes a shared non-selecting contract and a composite-only selection capability", () => {
    const hub = new MessageHub();
    const comp: IVmCollection<ComponentVM> = composite(hub);
    const grp: IVmCollection<ComponentVM> = group(hub);
    const selectable: ISelectableVmCollection<ComponentVM> = composite(hub);

    expect(comp.count).toBe(0);
    expect(grp.count).toBe(0);
    expect(selectable.current).toBeNull();
    expect("current" in grp).toBe(false);
  });
});

describe("COL-033", () => {
  it("moves forward and emits one move event", () => {
    const hub = new MessageHub();
    const [a, b, c] = [child(hub, "a"), child(hub, "b"), child(hub, "c")];
    const comp = composite(hub, [a, b, c]);
    comp.construct();
    const events: CollectionChangedEvent[] = [];
    comp.collectionChanged.subscribe((event) => events.push(event));

    comp.move(0, 2);

    expect([...comp]).toEqual([b, c, a]);
    expect(events).toEqual([expect.objectContaining({
      action: "move", oldItems: [a], newItems: [a], oldIndex: 0, newIndex: 2,
    })]);
  });
});

describe("COL-034", () => {
  it("moves backward on a group", () => {
    const hub = new MessageHub();
    const [a, b, c] = [child(hub, "a"), child(hub, "b"), child(hub, "c")];
    const grp = group(hub, [a, b, c]);
    grp.construct();
    const events: CollectionChangedEvent[] = [];
    grp.collectionChanged.subscribe((event) => events.push(event));

    grp.move(2, 0);

    expect([...grp]).toEqual([c, a, b]);
    expect(events).toEqual([expect.objectContaining({ action: "move", oldIndex: 2, newIndex: 0 })]);
  });
});

describe("COL-035", () => {
  it("treats a same-index move as a true no-op", () => {
    const hub = new MessageHub();
    const children = [child(hub, "a"), child(hub, "b"), child(hub, "c")];
    const comp = composite(hub, children);
    comp.construct();
    const events: CollectionChangedEvent[] = [];
    comp.collectionChanged.subscribe((event) => events.push(event));

    const batch = comp.batchUpdate();
    comp.move(1, 1);
    batch.dispose();

    expect([...comp]).toEqual(children);
    expect(events).toEqual([]);
  });
});

describe("COL-036", () => {
  it("rejects invalid bounds without mutation or events", () => {
    const hub = new MessageHub();
    const children = [child(hub, "a"), child(hub, "b"), child(hub, "c")];
    const comp = composite(hub, children);
    comp.construct();
    const events: CollectionChangedEvent[] = [];
    comp.collectionChanged.subscribe((event) => events.push(event));

    expect(() => comp.move(-1, 0)).toThrow(RangeError);
    expect(() => comp.move(0, 3)).toThrow(RangeError);
    expect([...comp]).toEqual(children);
    expect(events).toEqual([]);
  });
});

describe("COL-037", () => {
  it("preserves identity, parent, lifecycle, and current selection", () => {
    const hub = new MessageHub();
    const a = child(hub, "a");
    const comp = composite(hub, [a, child(hub, "b"), child(hub, "c")]);
    comp.construct();
    comp.current = a;

    comp.move(0, 2);

    expect(comp.at(2)).toBe(a);
    expect(comp.current).toBe(a);
    expect(a.isCurrent).toBe(true);
    expect(a.canDeselect()).toBe(true);
    expect(a.status).toBe(ConstructionStatus.Constructed);
  });
});

describe("COL-038", () => {
  it("collapses a batched move to one reset", () => {
    const hub = new MessageHub();
    const comp = composite(hub, [child(hub, "a"), child(hub, "b"), child(hub, "c")]);
    comp.construct();
    const events: CollectionChangedEvent[] = [];
    comp.collectionChanged.subscribe((event) => events.push(event));

    const batch = comp.batchUpdate();
    comp.move(0, 2);
    batch.dispose();

    expect(events.map(({ action }) => action)).toEqual(["reset"]);
  });
});

describe("COL-039", () => {
  it("does not reconstruct an auto-constructed child", () => {
    const hub = new MessageHub();
    let constructs = 0;
    const comp = composite(hub, [], true);
    comp.construct();
    const moved = child(hub, "moved", () => constructs++);
    comp.add(moved);
    comp.add(child(hub, "other"));

    comp.move(0, 1);

    expect(comp.at(1)).toBe(moved);
    expect(constructs).toBe(1);
  });
});
