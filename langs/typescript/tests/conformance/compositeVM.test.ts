import { describe, it, expect } from "vitest";
import { TestScheduler } from "rxjs/testing";
import { observeOn } from "rxjs";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMBase,
  ComponentVMOf,
  CompositeVM,
  CompositeVMOf,
  GroupVM,
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
    const isCurrentSenders: unknown[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) {
        propNames.push(m.propertyName);
        if (m.propertyName === "isCurrent") isCurrentSenders.push(m.sender);
      }
    });

    composite.selectComponent(vm);

    expect(composite.current).toBe(vm);
    expect(vm.isCurrent).toBe(true);
    expect(propNames).toContain("current");
    // Spec COMP-003: exactly one IsCurrent PropertyChangedMessage with Sender == vm.
    expect(isCurrentSenders).toEqual([vm]);
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
  it("AsyncSelection defers the Current change to the foreground scheduler", () => {
    const hub = makeHub();
    // A controllable virtual-time scheduler as the composite's foreground, so
    // the test can prove the selection is deferred (not synchronous) — mirrors
    // the Python TestDispatcher and C# TestScheduler bodies. queueScheduler
    // (immediate) would mask the deferral and pass even for synchronous select.
    const foreground = new TestScheduler((actual, expected) => {
      expect(actual).toEqual(expected);
    });
    const disp = new RxDispatcher(foreground, foreground);
    const vmA = makeChild(hub, "vmA");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .asyncSelection(true)
      .children(() => [vmA])
      .build();
    composite.construct();

    composite.selectComponent(vmA);

    // With AsyncSelection, Current does NOT change synchronously.
    expect(composite.current, "Current must not change synchronously").toBeNull();

    // Advancing the foreground scheduler completes the dispatch.
    foreground.flush();

    expect(composite.current).toBe(vmA);
  });

  it("drops the selection when the child is removed before the foreground dispatch", () => {
    // Regression: a child removed between selectComponent and the deferred
    // foreground dispatch must NOT become current (spec/06 §3 — a non-null
    // current is always a member of the children collection).
    const hub = makeHub();
    const foreground = new TestScheduler((actual, expected) => {
      expect(actual).toEqual(expected);
    });
    const disp = new RxDispatcher(foreground, foreground);
    const vmA = makeChild(hub, "vmA");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, disp)
      .asyncSelection(true)
      .children(() => [vmA])
      .build();
    composite.construct();

    composite.selectComponent(vmA); // deferred
    composite.remove(vmA); // removed before dispatch
    foreground.flush(); // deliver

    expect(composite.current).toBeNull();
    expect(vmA.isCurrent).toBe(false);
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
// CompositeVMOfBuilder.current(selector) — ADR-0042, spec/06 §3.2 (modeled)
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

// ---------------------------------------------------------------------------
// CompositeVMOfBuilder.onCurrentChanged(callback) — ADR-0042, spec/06 §3.2 (modeled)
// ---------------------------------------------------------------------------

describe("CompositeVMOfBuilder.onCurrentChanged(callback) (modeled)", () => {
  it("fires after each current change", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }
    const models: M[] = [{ id: 1 }, { id: 2 }];
    const observed: (ComponentVMOf<M> | null)[] = [];

    const composite = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("composite")
      .services(hub, disp)
      .childrenModels(() => models)
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    composite.construct();
    const second = composite.at(1);
    composite.selectComponent(second);
    composite.deselectComponent(second);

    expect(observed).toEqual([second, null]);
  });

  it("fires once for initial selector", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }
    const observed: (ComponentVMOf<M> | null)[] = [];

    const composite = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("composite")
      .services(hub, disp)
      .childrenModels(() => [{ id: 1 }])
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .current((xs) => [...xs][0] ?? null)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    composite.construct();

    expect(observed).toEqual([composite.at(0)]);
  });

  it("does not fire when selector returns null or out-of-set (ADR-0042 §5.4)", () => {
    const hub = makeHub();
    const disp = makeDisp();
    interface M { id: number }
    const observed: (ComponentVMOf<M> | null)[] = [];

    // Case 1: selector returns null
    const c1 = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("c-null")
      .services(hub, disp)
      .childrenModels(() => [{ id: 1 }])
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .current(() => null)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    c1.construct();
    expect(observed).toEqual([]);

    // Case 2: selector returns out-of-set
    const foreign = ComponentVMOf.builder<M>()
      .name("foreign")
      .model({ id: 999 })
      .services(hub, disp)
      .build();
    const c2 = CompositeVMOf.builder<M, ComponentVMOf<M>>()
      .name("c-foreign")
      .services(hub, disp)
      .childrenModels(() => [{ id: 1 }])
      .childModelToChildViewModel((m) =>
        ComponentVMOf.builder<M>().name(`vm-${m.id}`).model(m).services(hub, disp).build()
      )
      .current(() => foreign)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    c2.construct();
    expect(observed).toEqual([]);
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

// ---------------------------------------------------------------------------
// COMP-025 — Current(selector) builder hook drives initial selection during construct
// ---------------------------------------------------------------------------

describe("COMP-025", () => {
  it("Current(selector) builder hook drives initial selection during construct", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const children = ["a", "b", "c"].map((n) => makeChild(hub, n));

    let selectorCalls = 0;
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => children)
      .current((xs) => {
        selectorCalls++;
        return [...xs][1] ?? null;
      })
      .build();
    composite.construct();

    expect(composite.current).toBe(children[1]);
    expect(selectorCalls, "the selector must run exactly once during construct").toBe(1);

    // A null-returning selector leaves current null and publishes no
    // PropertyChangedMessage("current").
    const hub2 = makeHub();
    const children2 = ["a", "b", "c"].map((n) => makeChild(hub2, n));
    const propNames: string[] = [];
    hub2.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) propNames.push(m.propertyName);
    });
    const composite2 = CompositeVM.builder<ComponentVM>()
      .name("composite2")
      .services(hub2, disp)
      .children(() => children2)
      .current(() => null)
      .build();
    composite2.construct();

    expect(composite2.current).toBeNull();
    expect(propNames).not.toContain("current");
  });
});

// ---------------------------------------------------------------------------
// COMP-026 — OnCurrentChanged(callback) fires synchronously after each Current change
// ---------------------------------------------------------------------------

describe("COMP-026", () => {
  it("OnCurrentChanged(callback) fires synchronously after each Current change", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const children = ["a", "b"].map((n) => makeChild(hub, n));
    const observed: (ComponentVM | null)[] = [];

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => children)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    composite.construct();
    composite.selectComponent(children[1]!);
    composite.deselectComponent(children[1]!);

    expect(observed).toEqual([children[1], null]);

    // Combined current(first) + onCurrentChanged: the initial-selector
    // assignment fires the hook exactly once with the first child.
    const hub2 = makeHub();
    const children2 = ["a", "b"].map((n) => makeChild(hub2, n));
    const observed2: (ComponentVM | null)[] = [];
    const composite2 = CompositeVM.builder<ComponentVM>()
      .name("composite2")
      .services(hub2, disp)
      .children(() => children2)
      .current((xs) => [...xs][0] ?? null)
      .onCurrentChanged((vm) => observed2.push(vm))
      .build();
    composite2.construct();

    expect(observed2).toEqual([children2[0]]);
  });
});

// ---------------------------------------------------------------------------
// COMP-027 — Add sets a child's Parent; Remove clears it
// ---------------------------------------------------------------------------

describe("COMP-027", () => {
  it("Add sets a child's parent (selectable + select() delegates); Remove clears it", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => [] as ComponentVM[])
      .build();
    composite.construct();

    const child = makeChild(hub, "c");
    child.construct();

    // No parent yet → not selectable.
    expect(child.canSelect()).toBe(false);

    // Add wires parent → selectable, and select() delegates through it.
    composite.add(child);
    expect(child.canSelect()).toBe(true);
    child.select();
    expect(composite.current).toBe(child);
    expect(child.isCurrent).toBe(true);

    // Deselect, then remove: Remove clears parent → not selectable, select() no-op.
    child.deselect();
    expect(composite.current).toBeNull();
    expect(composite.remove(child)).toBe(true);
    expect(child.canSelect()).toBe(false);
    child.select(); // no-op: parent is null
    expect(composite.current).toBeNull();
  });
});

describe("COMP-038", () => {
  it("transfers a child from its previous parent", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const oldParent = CompositeVM.builder<ComponentVM>()
      .name("old").services(hub, dispatcher).children(() => []).build();
    const child = makeChild(hub, "c");
    oldParent.add(child);
    oldParent.construct();
    const group = GroupVM.builder<ComponentVM>()
      .name("group").services(hub, dispatcher).children(() => []).build();

    group.add(child);

    expect(oldParent.snapshot()).toEqual([]);
    expect(group.snapshot()).toEqual([child]);
    expect(child.status).toBe(ConstructionStatus.Constructed);
    expect(oldParent.remove(child)).toBe(false);

    const nextParent = CompositeVM.builder<ComponentVM>()
      .name("next").services(hub, dispatcher).children(() => []).build();
    nextParent.construct();
    nextParent.add(child);
    expect(group.snapshot()).toEqual([]);
    expect(child.canSelect()).toBe(true);
    child.select();
    expect(nextParent.current).toBe(child);
  });
});

describe("COMP-039", () => {
  it("rejects duplicate identity and ancestor cycles without mutation", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const parent = CompositeVM.builder<ComponentVM>()
      .name("parent").services(hub, dispatcher).children(() => []).build();
    const child = makeChild(hub, "child");
    parent.add(child);
    const events: CollectionChangedEvent[] = [];
    parent.collectionChanged.subscribe((event) => events.push(event));

    expect(() => parent.add(child)).toThrow(/already contains/);
    expect(parent.snapshot()).toEqual([child]);
    expect(events).toEqual([]);

    const outer = CompositeVM.builder<ComponentVMBase>()
      .name("outer").services(hub, dispatcher).children(() => []).build();
    const inner = CompositeVM.builder<ComponentVMBase>()
      .name("inner").services(hub, dispatcher).children(() => []).build();
    outer.add(inner);
    expect(() => inner.add(outer)).toThrow(/parent cycle/);
    expect(outer.snapshot()).toEqual([inner]);
    expect(inner.snapshot()).toEqual([]);
  });
});

describe("COMP-040", () => {
  it("rejects duplicate identities in composite and group factory populations", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const child = makeChild(hub, "duplicate");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite").services(hub, dispatcher)
      .children(() => [child, child]).build();
    const group = GroupVM.builder<ComponentVM>()
      .name("group").services(hub, dispatcher)
      .children(() => [child, child]).build();

    expect(() => composite.construct()).toThrow(/duplicate child identity/);
    expect(() => group.construct()).toThrow(/duplicate child identity/);
    expect(composite.snapshot()).toEqual([]);
    expect(group.snapshot()).toEqual([]);
  });

  it("rejects reparenting from an auto-construct hook before admission commits", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const source = CompositeVM.builder<ComponentVM>()
      .name("source").services(hub, dispatcher)
      .children(() => []).autoConstructOnAdd(true).build();
    const destination = GroupVM.builder<ComponentVM>()
      .name("destination").services(hub, dispatcher)
      .children(() => []).build();
    let child: ComponentVM;
    child = ComponentVM.builder().name("child").services(hub, dispatcher)
      .onConstruct(() => destination.add(child)).build();
    source.construct();
    const events: string[] = [];
    source.collectionChanged.subscribe(() => events.push("source"));
    destination.collectionChanged.subscribe(() => events.push("destination"));

    expect(() => source.add(child)).toThrow(/ownership transaction is already in progress/);
    expect(source.snapshot()).toEqual([]);
    expect(destination.snapshot()).toEqual([]);
    expect(events).toEqual([]);
  });

  it("aborts composite and group admission when auto-construction disposes the destination", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite").services(hub, dispatcher)
      .children(() => []).autoConstructOnAdd(true).build();
    const group = GroupVM.builder<ComponentVM>()
      .name("group").services(hub, dispatcher)
      .children(() => []).autoConstructOnAdd(true).build();
    const compositeChild = ComponentVM.builder().name("composite-child")
      .services(hub, dispatcher).onConstruct(() => composite.dispose()).build();
    const groupChild = ComponentVM.builder().name("group-child")
      .services(hub, dispatcher).onConstruct(() => group.dispose()).build();
    composite.construct();
    group.construct();

    expect(() => composite.add(compositeChild)).toThrow(/disposing/);
    expect(() => group.add(groupChild)).toThrow(/disposing/);
    expect(composite.snapshot()).toEqual([]);
    expect(group.snapshot()).toEqual([]);
    expect(compositeChild._parent).toBeNull();
    expect(groupChild._parent).toBeNull();
  });

  it("defers old-composite disposal until a successful transfer commits", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const oldParent = CompositeVM.builder<ComponentVM>()
      .name("old").services(hub, dispatcher).children(() => []).build();
    const destination = GroupVM.builder<ComponentVM>()
      .name("destination").services(hub, dispatcher)
      .children(() => []).autoConstructOnAdd(true).build();
    const child = ComponentVM.builder().name("child").services(hub, dispatcher)
      .onConstruct(() => oldParent.dispose()).build();
    oldParent.add(child);
    destination.construct();

    destination.add(child);

    expect(oldParent.status).toBe(ConstructionStatus.Disposed);
    expect(oldParent.snapshot()).toEqual([]);
    expect(destination.snapshot()).toEqual([child]);
    expect(child.status).toBe(ConstructionStatus.Constructed);
    expect(child._parent?.owner).toBe(destination);
  });

  it("rolls back before deferred old-group disposal after transfer failure", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const oldParent = GroupVM.builder<ComponentVM>()
      .name("old").services(hub, dispatcher).children(() => []).build();
    const destination = CompositeVM.builder<ComponentVM>()
      .name("destination").services(hub, dispatcher)
      .children(() => []).autoConstructOnAdd(true).build();
    const child = ComponentVM.builder().name("child").services(hub, dispatcher)
      .onConstruct(() => {
        oldParent.dispose();
        throw new Error("boom");
      }).build();
    oldParent.add(child);
    destination.construct();

    expect(() => destination.add(child)).toThrow("boom");

    expect(oldParent.status).toBe(ConstructionStatus.Disposed);
    expect(oldParent.snapshot()).toEqual([child]);
    expect(destination.snapshot()).toEqual([]);
    expect(child.status).toBe(ConstructionStatus.Disposed);
    expect(child._parent?.owner).toBe(oldParent);
  });

  it("restores parent, index, current, and lifecycle when construction fails", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const child = ComponentVM.builder()
      .name("failing")
      .services(hub, dispatcher)
      .onConstruct(() => { throw new Error("boom"); })
      .build();
    const sibling = makeChild(hub, "sibling");
    const oldParent = CompositeVM.builder<ComponentVM>()
      .name("old").services(hub, dispatcher).children(() => []).build();
    oldParent.add(sibling);
    oldParent.add(child);
    oldParent.current = child;
    const destination = GroupVM.builder<ComponentVM>()
      .name("destination")
      .services(hub, dispatcher)
      .children(() => [])
      .autoConstructOnAdd(true)
      .build();
    destination.construct();
    const events: string[] = [];
    oldParent.collectionChanged.subscribe(() => events.push("old"));
    destination.collectionChanged.subscribe(() => events.push("new"));

    expect(() => destination.add(child)).toThrow("boom");
    expect(oldParent.snapshot()).toEqual([sibling, child]);
    expect(oldParent.current).toBe(child);
    expect(child.isCurrent).toBe(true);
    expect(child.status).toBe(ConstructionStatus.Destructed);
    expect(destination.snapshot()).toEqual([]);
    expect(events).toEqual([]);
  });

  it("rolls back an entire lazy population and remains retryable", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    let destination: GroupVM<ComponentVM>;
    const first = ComponentVM.builder()
      .name("first")
      .services(hub, dispatcher)
      .onConstruct(() => { expect(destination.snapshot()).toHaveLength(2); })
      .build();
    const blocker = ComponentVM.builder()
      .name("bulk-failing")
      .services(hub, dispatcher)
      .onConstruct(() => { throw new Error("boom"); })
      .build();
    const oldParent = CompositeVM.builder<ComponentVM>()
      .name("bulk-old").services(hub, dispatcher).children(() => []).build();
    oldParent.add(first);
    const batch = [first, blocker];
    destination = GroupVM.builder<ComponentVM>()
      .name("bulk-destination")
      .services(hub, dispatcher)
      .children(() => batch)
      .build();
    const events: string[] = [];
    oldParent.collectionChanged.subscribe(() => events.push("old"));
    destination.collectionChanged.subscribe(() => events.push("new"));

    expect(() => destination.construct()).toThrow("boom");

    expect(oldParent.snapshot()).toEqual([first]);
    expect(first.status).toBe(ConstructionStatus.Destructed);
    expect(destination.snapshot()).toEqual([]);
    expect(events).toEqual([]);
    batch.length = 0;
    destination.construct();
    expect(destination.snapshot()).toEqual([]);
  });

  it("surfaces a lifecycle compensation failure after restoring membership", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const compensated = ComponentVM.builder()
      .name("compensated")
      .services(hub, dispatcher)
      .onDestruct(() => { throw new Error("compensation failed"); })
      .build();
    const blocker = ComponentVM.builder()
      .name("blocker")
      .services(hub, dispatcher)
      .onConstruct(() => { throw new Error("population failed"); })
      .build();
    const destination = GroupVM.builder<ComponentVM>()
      .name("destination")
      .services(hub, dispatcher)
      .children(() => [compensated, blocker])
      .build();

    let caught: unknown;
    try {
      destination.construct();
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(Error);
    const rollback = caught as Error & { rollbackError: unknown };
    expect(rollback.name).toBe("ContainerRollbackError");
    expect((rollback.cause as Error).message).toBe("population failed");
    expect((rollback.rollbackError as Error).message).toBe("compensation failed");
    expect(destination.snapshot()).toEqual([]);
  });
});

describe("COMP-041", () => {
  it("publishes old removal before new addition after commit", () => {
    const hub = makeHub();
    const dispatcher = makeDisp();
    const oldParent = CompositeVM.builder<ComponentVM>()
      .name("old").services(hub, dispatcher).children(() => []).build();
    const child = makeChild(hub, "child");
    oldParent.add(child);
    const destination = GroupVM.builder<ComponentVM>()
      .name("destination").services(hub, dispatcher).children(() => []).build();
    const observed: string[] = [];
    oldParent.collectionChanged.subscribe((event) => {
      expect(event.action).toBe("remove");
      expect(oldParent.snapshot()).not.toContain(child);
      expect(destination.snapshot()).toContain(child);
      observed.push("old:remove");
    });
    destination.collectionChanged.subscribe((event) => {
      expect(event.action).toBe("add");
      expect(oldParent.snapshot()).not.toContain(child);
      expect(destination.snapshot()).toContain(child);
      observed.push("new:add");
    });

    destination.add(child);

    expect(observed).toEqual(["old:remove", "new:add"]);
  });
});
