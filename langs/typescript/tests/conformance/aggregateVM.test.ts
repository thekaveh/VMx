import { describe, it, expect } from "vitest";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM5,
  PropertyChangedMessage,
  ConstructionStatusChangedMessage,
} from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }
function makeChild(hub: MessageHub, name: string) {
  return ComponentVM.builder().name(name).services(hub, makeDisp()).build();
}

// ---------------------------------------------------------------------------
// AGG-001
// ---------------------------------------------------------------------------

describe("AGG-001", () => {
  it("Arity-1 ComponentN factory invoked on construct", () => {
    const hub = makeHub();
    const child = makeChild(hub, "c1");
    const agg = AggregateVM1.builder<ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => child)
      .build();

    agg.construct();

    expect(agg.component1).toBe(child);
    expect(agg.component1?.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// AGG-002
// ---------------------------------------------------------------------------

describe("AGG-002", () => {
  it("Arity-2 both components reach Constructed in parallel", () => {
    const hub = makeHub();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const agg = AggregateVM2.builder<ComponentVM, ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => c1)
      .component2(() => c2)
      .build();

    agg.construct();

    expect(agg.component1?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.component2?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// AGG-003
// ---------------------------------------------------------------------------

describe("AGG-003", () => {
  it("Arity-5 all five components reach Constructed before parent", () => {
    const hub = makeHub();
    const cs = [1, 2, 3, 4, 5].map((i) => makeChild(hub, `c${i}`));
    const agg = AggregateVM5.builder<
      ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
    >()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => cs[0]!)
      .component2(() => cs[1]!)
      .component3(() => cs[2]!)
      .component4(() => cs[3]!)
      .component5(() => cs[4]!)
      .build();

    // When the parent's Constructed message fires, all children must already be Constructed.
    let allChildrenConstructedBeforeParent = false;
    hub.messages.subscribe((m) => {
      if (
        m instanceof ConstructionStatusChangedMessage &&
        m.status === ConstructionStatus.Constructed &&
        m.senderObject === agg
      ) {
        allChildrenConstructedBeforeParent =
          cs.every((c) => c.status === ConstructionStatus.Constructed);
      }
    });

    agg.construct();

    expect(agg.status).toBe(ConstructionStatus.Constructed);
    expect(allChildrenConstructedBeforeParent).toBe(true);
    for (const c of cs) {
      expect(c.status).toBe(ConstructionStatus.Constructed);
    }
  });
});

// ---------------------------------------------------------------------------
// AGG-004
// ---------------------------------------------------------------------------

describe("AGG-004", () => {
  it("ComponentN property change fires on construct", () => {
    const hub = makeHub();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const c3 = makeChild(hub, "c3");
    const agg = AggregateVM3.builder<ComponentVM, ComponentVM, ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => c1)
      .component2(() => c2)
      .component3(() => c3)
      .build();

    const propNames: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.senderObject === agg) {
        propNames.push(m.propertyName);
      }
    });

    agg.construct();

    expect(propNames).toContain("Component1");
    expect(propNames).toContain("Component2");
    expect(propNames).toContain("Component3");
  });
});

// ---------------------------------------------------------------------------
// AGG-005
// ---------------------------------------------------------------------------

describe("AGG-005", () => {
  it("Destruction waits for all children Destructed", () => {
    const hub = makeHub();
    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const agg = AggregateVM2.builder<ComponentVM, ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => c1)
      .component2(() => c2)
      .build();
    agg.construct();

    agg.destruct();

    expect(agg.component1?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.component2?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.status).toBe(ConstructionStatus.Destructed);
  });
});
