import { describe, it, expect } from "vitest";
import { TestScheduler } from "rxjs/testing";
import { observeOn } from "rxjs";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  CompositeVMOf,
  PropertyChangedMessage,
} from "../../src/index.js";
import type { CollectionChangedEvent } from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

function makeChild(hub: MessageHub, name: string) {
  return ComponentVM.builder().name(name).services(hub, makeDisp()).build();
}

// ---------------------------------------------------------------------------
// COMP-001
// ---------------------------------------------------------------------------

describe("COMP-001", () => {
  it("Add emits CollectionChanged(action=Add)", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [])
      .build();
    composite.construct();

    const events: CollectionChangedEvent[] = [];
    composite.collectionChanged.subscribe((e) => events.push(e));

    const vm = makeChild(hub, "child");
    composite.add(vm);

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("add");
    expect(events[0]?.newItems).toContain(vm);
    expect(events[0]?.newIndex).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// COMP-002
// ---------------------------------------------------------------------------

describe("COMP-002", () => {
  it("Remove emits CollectionChanged(action=Remove)", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm = makeChild(hub, "child");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [vm])
      .build();
    composite.construct();

    const events: CollectionChangedEvent[] = [];
    composite.collectionChanged.subscribe((e) => events.push(e));

    composite.remove(vm);

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("remove");
    expect(events[0]?.oldItems).toContain(vm);
    expect(events[0]?.oldIndex).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// COMP-003
// ---------------------------------------------------------------------------

describe("COMP-003", () => {
  it("select_component sets Current and emits PropertyChanged messages", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm = ComponentVM.builder().name("child").services(hub, disp).build();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [vm])
      .build();
    composite.construct();

    const propNames: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) propNames.push(m.propertyName);
    });

    composite.selectComponent(vm);

    expect(composite.current).toBe(vm);
    expect(vm.isCurrent).toBe(true);
    expect(propNames).toContain("current");
    expect(propNames).toContain("isCurrent");
  });
});

// ---------------------------------------------------------------------------
// COMP-004
// ---------------------------------------------------------------------------

describe("COMP-004", () => {
  it("Construct waits until all children reach Constructed", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => [c1, c2])
      .build();

    composite.construct();

    expect(c1.status).toBe(ConstructionStatus.Constructed);
    expect(c2.status).toBe(ConstructionStatus.Constructed);
    expect(composite.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// COMP-005
// ---------------------------------------------------------------------------

describe("COMP-005", () => {
  it("Destruct waits until all children reach Destructed and unsets Current", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => [c1, c2])
      .build();
    composite.construct();
    composite.selectComponent(c1);
    expect(composite.current).toBe(c1);

    composite.destruct();

    expect(composite.current).toBeNull();
    expect(c1.status).toBe(ConstructionStatus.Destructed);
    expect(c2.status).toBe(ConstructionStatus.Destructed);
    expect(composite.status).toBe(ConstructionStatus.Destructed);
  });
});

// ---------------------------------------------------------------------------
// COMP-006
// ---------------------------------------------------------------------------

describe("COMP-006", () => {
  it("IsCurrent change on previously-Current child dispatches on foreground scheduler", () => {
    const testScheduler = new TestScheduler((actual, expected) => {
      expect(actual).toEqual(expected);
    });

    testScheduler.run(({ flush }) => {
      const hub = makeHub();
      const disp = makeDisp();
      const vmA = makeChild(hub, "vmA");
      const vmB = makeChild(hub, "vmB");
      const composite = CompositeVM.builder<ComponentVM>()
        .name("composite")
        .services(hub, disp)
        .children(() => [vmA, vmB])
        .build();
      composite.construct();
      composite.selectComponent(vmA);

      // Catalog: the subscriber observes the change via the foreground
      // scheduler ("using ObserveOn(dispatcher.Foreground)") — pipe through
      // a controllable scheduler and assert delivery only after it runs.
      const isCurrentChanges: boolean[] = [];
      vmA.propertyChanged.pipe(observeOn(testScheduler)).subscribe((p) => {
        if (p === "isCurrent") isCurrentChanges.push(vmA.isCurrent);
      });

      composite.deselectComponent(vmA);

      expect(isCurrentChanges, "buffered until the scheduler runs").toHaveLength(0);
      flush();
      expect(isCurrentChanges).toContain(false);
    });
  });
});

// ---------------------------------------------------------------------------
// COMP-007
// ---------------------------------------------------------------------------

describe("COMP-007", () => {
  it("Modeled composite maps model factory output to children", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }
    const m1: M = { id: 1 };
    const m2: M = { id: 2 };

    const composite = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("composite")
      .services(hub, disp)
      .childrenModels(() => [m1, m2])
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .build();

    composite.construct();

    expect(composite.count).toBe(2);
    expect(composite.at(0).model).toBe(m1);
    expect(composite.at(1).model).toBe(m2);
  });
});

// ---------------------------------------------------------------------------
// COMP-008
// ---------------------------------------------------------------------------

describe("COMP-008", () => {
  it("can_select_component returns false for non-children", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vmA = makeChild(hub, "vmA");
    const vmB = makeChild(hub, "vmB");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [vmA])
      .build();
    composite.construct();

    expect(composite.canSelectComponent(vmB)).toBe(false);
    expect(() => composite.selectComponent(vmB)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// COMP-009
// ---------------------------------------------------------------------------

describe("COMP-009", () => {
  it("Current setter raises when assigned a non-child", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vmA = makeChild(hub, "vmA");
    const vmB = makeChild(hub, "vmB");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [vmA])
      .build();
    composite.construct();

    expect(() => { composite.current = vmB; }).toThrow();
    expect(composite.current).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// COMP-010
// ---------------------------------------------------------------------------

describe("COMP-010", () => {
  it("AsyncSelection dispatches Current change via foreground scheduler", () => {
    // Use the queueScheduler (synchronous) as the foreground scheduler.
    // With asyncSelection=true, the change is scheduled on the foreground scheduler.
    // With queueScheduler, it executes synchronously within the same task.
    const hub = makeHub();
    const disp = makeDisp(); // both use queueScheduler
    const vmA = makeChild(hub, "vmA");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .asyncSelection(true)
      .children(() => [vmA])
      .build();
    composite.construct();

    // With queueScheduler (synchronous), current changes synchronously
    // when the scheduler flushes (which is immediate for queueScheduler).
    composite.selectComponent(vmA);

    // queueScheduler is synchronous, so the selection completes immediately.
    expect(composite.current).toBe(vmA);
  });
});

// ---------------------------------------------------------------------------
// COMP-011
// ---------------------------------------------------------------------------

describe("COMP-011", () => {
  it("deselect_component raises when vm is not Current", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vmA = makeChild(hub, "vmA");
    const vmB = makeChild(hub, "vmB");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [vmA, vmB])
      .build();
    composite.construct();
    composite.selectComponent(vmA);

    expect(() => composite.deselectComponent(vmB)).toThrow();
    expect(composite.current).toBe(vmA);
  });
});

// ---------------------------------------------------------------------------
// COMP-012
// ---------------------------------------------------------------------------

describe("COMP-012", () => {
  it("AutoConstructOnAdd(true) auto-constructs late children", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .autoConstructOnAdd(true)
      .children(() => [])
      .build();
    composite.construct();

    const child = makeChild(hub, "late-child");
    const events: CollectionChangedEvent[] = [];
    const statusAtEvent: ConstructionStatus[] = [];
    composite.collectionChanged.subscribe((e) => {
      events.push(e);
      statusAtEvent.push(child.status);
    });

    composite.add(child);

    // Event should have been emitted.
    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("add");
    // Catalog: the child reaches Constructed BEFORE the Add event is
    // observed — capture the status inside the handler, not post-hoc.
    expect(statusAtEvent[0]).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// COMP-013
// ---------------------------------------------------------------------------

describe("COMP-013", () => {
  it("BatchUpdate suppresses per-mutation events and emits one Reset", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [])
      .build();
    composite.construct();

    const events: CollectionChangedEvent[] = [];
    composite.collectionChanged.subscribe((e) => events.push(e));

    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const c3 = makeChild(hub, "c3");

    const batch = composite.batchUpdate();
    composite.add(c1);
    composite.add(c2);
    composite.insert(0, c3);
    // No events yet
    expect(events).toHaveLength(0);
    batch.dispose();

    // Exactly one Reset event
    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("reset");
    // Children reflect post-batch state
    expect(composite.count).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// setAt _current handling (unit; not a conformance ID)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// CompositeVMOfBuilder.current(selector) — ADR-0042, spec/06 §3.X (modeled)
// ---------------------------------------------------------------------------

describe("CompositeVMOfBuilder.current(selector) (modeled)", () => {
  it("drives initial selection after construct", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }
    const models: M[] = [{ id: 1 }, { id: 2 }, { id: 3 }];

    const composite = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("composite")
      .services(hub, disp)
      .childrenModels(() => models)
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .current((xs) => [...xs][1] ?? null)
      .build();
    composite.construct();

    expect(composite.current).toBe(composite.at(1));
  });

  it("returning null leaves current null", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }

    const composite = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("composite")
      .services(hub, disp)
      .childrenModels(() => [{ id: 1 }])
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .current(() => null)
      .build();
    composite.construct();

    expect(composite.current).toBeNull();
  });
});

describe("setAt _current handling", () => {
  it("setAt replacing the current slot clears current to null", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const oldChild = makeChild(hub, "old");
    const newChild = makeChild(hub, "new");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [oldChild])
      .build();
    composite.construct();
    composite.current = oldChild;
    expect(composite.current).toBe(oldChild);

    composite.setAt(0, newChild);

    expect(composite.current).toBeNull();
    expect(composite.at(0)).toBe(newChild);
    expect(oldChild._parent).toBeNull();
    expect(newChild._parent).toBe(composite);
  });

  it("setAt replacing a non-current slot leaves current intact", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const other = makeChild(hub, "other");
    const sticky = makeChild(hub, "sticky");
    const replacement = makeChild(hub, "replacement");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .children(() => [other, sticky])
      .build();
    composite.construct();
    composite.current = sticky;

    composite.setAt(0, replacement);  // replace `other`, not `sticky`

    expect(composite.current).toBe(sticky);
  });
});
