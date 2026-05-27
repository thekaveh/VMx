import { describe, it, expect } from "vitest";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  GroupVM,
} from "../../src/index.js";
import type { CollectionChangedEvent } from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }
function makeChild(hub: MessageHub, name: string) {
  return ComponentVM.builder().name(name).services(hub, makeDisp()).build();
}

// ---------------------------------------------------------------------------
// GRP-001
// ---------------------------------------------------------------------------

describe("GRP-001", () => {
  it("Add emits CollectionChanged(action=Add)", () => {
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    group.construct();

    const events: CollectionChangedEvent[] = [];
    group.collectionChanged.subscribe((e) => events.push(e));

    const vm = makeChild(hub, "c1");
    group.add(vm);

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("add");
    expect(events[0]?.newItems).toContain(vm);
    expect(events[0]?.newIndex).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// GRP-002
// ---------------------------------------------------------------------------

describe("GRP-002", () => {
  it("Group lacks child-navigation and child-selection members", () => {
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [])
      .build();

    // No 'current' property
    expect("current" in group).toBe(false);
    // No selectComponent / deselectComponent / canSelectComponent
    expect("selectComponent" in group).toBe(false);
    expect("deselectComponent" in group).toBe(false);
    expect("canSelectComponent" in group).toBe(false);

    // SelectCommand and DeselectCommand ARE present (own-selection within parent).
    // We verify they're non-null and expose the ICommand surface (canExecute).
    expect(group.selectCommand).not.toBeNull();
    expect(typeof group.selectCommand.canExecute).toBe("function");
    expect(group.deselectCommand).not.toBeNull();
    expect(typeof group.deselectCommand.canExecute).toBe("function");

    // SelectNextCommand and SelectPreviousCommand are present but always-false.
    expect(group.selectNextCommand).not.toBeNull();
    expect(group.selectPreviousCommand).not.toBeNull();
    expect(group.selectNextCommand.canExecute()).toBe(false);
    expect(group.selectPreviousCommand.canExecute()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// GRP-003
// ---------------------------------------------------------------------------

describe("GRP-003", () => {
  it("Construct waits until all children reach Constructed", () => {
    const hub = makeHub();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [c1, c2])
      .build();

    group.construct();

    expect(c1.status).toBe(ConstructionStatus.Constructed);
    expect(c2.status).toBe(ConstructionStatus.Constructed);
    expect(group.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// GRP-004
// ---------------------------------------------------------------------------

describe("GRP-004", () => {
  it("Destruct waits until all children reach Destructed", () => {
    const hub = makeHub();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [c1, c2])
      .build();
    group.construct();

    group.destruct();

    expect(c1.status).toBe(ConstructionStatus.Destructed);
    expect(c2.status).toBe(ConstructionStatus.Destructed);
    expect(group.status).toBe(ConstructionStatus.Destructed);
  });
});

// ---------------------------------------------------------------------------
// GRP-005
// ---------------------------------------------------------------------------

describe("GRP-005", () => {
  it("AutoConstructOnAdd(true) auto-constructs late children", () => {
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .autoConstructOnAdd(true)
      .children(() => [])
      .build();
    group.construct();

    const child = makeChild(hub, "late");
    const events: CollectionChangedEvent[] = [];
    group.collectionChanged.subscribe((e) => events.push(e));

    group.add(child);

    expect(child.status).toBe(ConstructionStatus.Constructed);
    expect(events).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// GRP-006
// ---------------------------------------------------------------------------

describe("GRP-006", () => {
  it("BatchUpdate suppresses per-mutation events and emits one Reset", () => {
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    group.construct();

    const events: CollectionChangedEvent[] = [];
    group.collectionChanged.subscribe((e) => events.push(e));

    const batch = group.batchUpdate();
    group.add(makeChild(hub, "c1"));
    group.add(makeChild(hub, "c2"));
    expect(events).toHaveLength(0);
    batch.dispose();

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("reset");
  });
});
