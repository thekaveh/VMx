import { describe, it, expect } from "vitest";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM4,
  AggregateVM5,
  AggregateVM6,
  ForwardingComponentVM,
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
  it("Arity-1 ComponentN factory invoked lazily, exactly once, on construct", () => {
    const hub = makeHub();
    let factoryCalls = 0;
    let child: ComponentVM | null = null;
    const agg = AggregateVM1.builder<ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => {
        factoryCalls++;
        child = makeChild(hub, "c1");
        return child;
      })
      .build();

    // Lazy: the factory has not run and the slot is empty before construct().
    expect(factoryCalls, "factory must not run before construct()").toBe(0);
    expect(agg.component1).toBeNull();

    agg.construct();

    expect(factoryCalls, "factory must run exactly once during construct()").toBe(1);
    expect(agg.component1).toBe(child);
    expect(agg.component1?.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// AGG-002
// ---------------------------------------------------------------------------

describe("AGG-002", () => {
  it("Arity-2 both components reach Constructed", () => {
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
        m.sender === agg
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
      if (m instanceof PropertyChangedMessage && m.sender === agg) {
        propNames.push(m.propertyName);
      }
    });

    agg.construct();

    expect(propNames).toContain("component1");
    expect(propNames).toContain("component2");
    expect(propNames).toContain("component3");
    // Exactly the three slot changes fire — no duplicate/spurious slot
    // property-change (matches the Python AGG-004 `len == 3` assertion).
    expect(propNames).toHaveLength(3);
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

// ---------------------------------------------------------------------------
// AGG-006
// ---------------------------------------------------------------------------

describe("AGG-006", () => {
  it("Arity-6 all six components reach Constructed; destruction waits for all", () => {
    const hub = makeHub();
    const cs = [1, 2, 3, 4, 5, 6].map((i) => makeChild(hub, `c${i}`));
    const agg = AggregateVM6.builder<
      ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
    >()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => cs[0]!)
      .component2(() => cs[1]!)
      .component3(() => cs[2]!)
      .component4(() => cs[3]!)
      .component5(() => cs[4]!)
      .component6(() => cs[5]!)
      .build();

    agg.construct();

    for (const c of cs) {
      expect(c.status).toBe(ConstructionStatus.Constructed);
    }
    expect(agg.status).toBe(ConstructionStatus.Constructed);

    agg.destruct();

    for (const c of cs) {
      expect(c.status).toBe(ConstructionStatus.Destructed);
    }
    expect(agg.status).toBe(ConstructionStatus.Destructed);
  });
});

// AggregateVM4 smoke test — not a separate conformance ID, but a guard
// against the arity-4 type-and-builder shipping as dead public API.
// AGG-001..005 cover arity-1/2/3/5 explicitly; arity-4 was previously
// untested in any flavor's TS suite (Python and C# both exercise it).
describe("AggregateVM4 smoke", () => {
  it("construct/destruct populates and tears down all four slots", () => {
    const hub = makeHub();
    const cs = [1, 2, 3, 4].map((i) => makeChild(hub, `c${i}`));
    const agg = AggregateVM4.builder<
      ComponentVM, ComponentVM, ComponentVM, ComponentVM
    >()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => cs[0]!)
      .component2(() => cs[1]!)
      .component3(() => cs[2]!)
      .component4(() => cs[3]!)
      .build();

    agg.construct();
    expect(agg.component1?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.component2?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.component3?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.component4?.status).toBe(ConstructionStatus.Constructed);
    expect(agg.status).toBe(ConstructionStatus.Constructed);

    agg.destruct();
    expect(agg.component1?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.component2?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.component3?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.component4?.status).toBe(ConstructionStatus.Destructed);
    expect(agg.status).toBe(ConstructionStatus.Destructed);
  });
});

describe("AggregateVM reconstruct disposes previous slot", () => {
  it("AggregateVM1.reconstruct disposes the previous _component1", () => {
    const hub = makeHub();
    let nextName = 0;
    const agg = AggregateVM1.builder<ComponentVM>()
      .name("agg")
      .services(hub, makeDisp())
      .component1(() => makeChild(hub, `slot${++nextName}`))
      .build();

    agg.construct();
    const first = agg.component1;
    expect(first).not.toBeNull();
    expect(first?.status).toBe(ConstructionStatus.Constructed);

    // reconstruct() = destruct + construct; with the fix the previous
    // slot is disposed before the factory yields a fresh instance.
    agg.reconstruct();

    const second = agg.component1;
    expect(second).not.toBeNull();
    expect(second).not.toBe(first);
    expect(second?.status).toBe(ConstructionStatus.Constructed);
    expect(first?.status).toBe(ConstructionStatus.Disposed);
  });

  // LIFE-013 reconstruct-disposes-prior-slots over arities 2..6 — cross-flavor
  // parity with the Python parametric test in
  // langs/python/tests/unit/aggregates/test_aggregate_vm.py
  // (test_reconstruct_disposes_prior_slots_before_overwriting).
  it.each([2, 3, 4, 5, 6])(
    "AggregateVM%d.reconstruct disposes every previous slot",
    (arity) => {
      const hub = makeHub();
      let nextName = 0;
      const factory = () => makeChild(hub, `slot${++nextName}`);

      const firstSlots: ComponentVM[] = [];
      let reconstruct: () => void;
      let readSlots: () => (ComponentVM | null)[];

      switch (arity) {
        case 2: {
          const agg = AggregateVM2.builder<ComponentVM, ComponentVM>()
            .name("agg2").services(hub, makeDisp())
            .component1(factory).component2(factory).build();
          agg.construct();
          firstSlots.push(agg.component1!, agg.component2!);
          reconstruct = () => { agg.reconstruct(); };
          readSlots = () => [agg.component1, agg.component2];
          break;
        }
        case 3: {
          const agg = AggregateVM3.builder<ComponentVM, ComponentVM, ComponentVM>()
            .name("agg3").services(hub, makeDisp())
            .component1(factory).component2(factory).component3(factory).build();
          agg.construct();
          firstSlots.push(agg.component1!, agg.component2!, agg.component3!);
          reconstruct = () => { agg.reconstruct(); };
          readSlots = () => [agg.component1, agg.component2, agg.component3];
          break;
        }
        case 4: {
          const agg = AggregateVM4.builder<ComponentVM, ComponentVM, ComponentVM, ComponentVM>()
            .name("agg4").services(hub, makeDisp())
            .component1(factory).component2(factory).component3(factory).component4(factory).build();
          agg.construct();
          firstSlots.push(agg.component1!, agg.component2!, agg.component3!, agg.component4!);
          reconstruct = () => { agg.reconstruct(); };
          readSlots = () => [agg.component1, agg.component2, agg.component3, agg.component4];
          break;
        }
        case 5: {
          const agg = AggregateVM5.builder<ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM>()
            .name("agg5").services(hub, makeDisp())
            .component1(factory).component2(factory).component3(factory).component4(factory).component5(factory).build();
          agg.construct();
          firstSlots.push(agg.component1!, agg.component2!, agg.component3!, agg.component4!, agg.component5!);
          reconstruct = () => { agg.reconstruct(); };
          readSlots = () => [agg.component1, agg.component2, agg.component3, agg.component4, agg.component5];
          break;
        }
        case 6: {
          const agg = AggregateVM6.builder<
            ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
          >()
            .name("agg6").services(hub, makeDisp())
            .component1(factory).component2(factory).component3(factory).component4(factory).component5(factory).component6(factory).build();
          agg.construct();
          firstSlots.push(
            agg.component1!, agg.component2!, agg.component3!,
            agg.component4!, agg.component5!, agg.component6!,
          );
          reconstruct = () => { agg.reconstruct(); };
          readSlots = () => [agg.component1, agg.component2, agg.component3, agg.component4, agg.component5, agg.component6];
          break;
        }
        default:
          throw new Error(`unsupported arity ${arity}`);
      }

      firstSlots.forEach((s) => expect(s.status).toBe(ConstructionStatus.Constructed));

      reconstruct();

      const fresh = readSlots();
      fresh.forEach((s) => expect(s).not.toBeNull());
      firstSlots.forEach((first, i) => {
        expect(fresh[i]).not.toBe(first);
        expect(fresh[i]?.status).toBe(ConstructionStatus.Constructed);
        expect(first.status).toBe(ConstructionStatus.Disposed);
      });
    },
  );
});

describe("Aggregate fixed-slot ownership", () => {
  it("rejects forwarding aliases of one canonical component", () => {
    const hub = makeHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("model")
      .services(hub, makeDisp())
      .build();
    const first = new ForwardingComponentVM(inner);
    const second = new ForwardingComponentVM(inner);
    const duplicate = AggregateVM2.builder<ForwardingComponentVM<string>, ForwardingComponentVM<string>>()
      .name("duplicate")
      .services(hub, makeDisp())
      .component1(() => first)
      .component2(() => second)
      .build();

    expect(() => duplicate.construct()).toThrow(/duplicate canonical identity/);
    expect(duplicate.component1).toBeNull();
    expect(duplicate.component2).toBeNull();

    const composite = CompositeVM.builder<ComponentVMOf<string>>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => [inner])
      .build();
    composite.construct();
    const ownedAlias = AggregateVM1.builder<ForwardingComponentVM<string>>()
      .name("owned-alias")
      .services(hub, makeDisp())
      .component1(() => new ForwardingComponentVM(inner))
      .build();

    expect(() => ownedAlias.construct()).toThrow(/already owned/);
    expect(composite.snapshot()).toEqual([inner]);
    expect(ownedAlias.component1).toBeNull();
  });

  it("rejects an already-owned factory result without mutating either container", () => {
    const hub = makeHub();
    const child = makeChild(hub, "child");
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => [child])
      .build();
    composite.construct();
    const aggregate = AggregateVM1.builder<ComponentVM>()
      .name("aggregate")
      .services(hub, makeDisp())
      .component1(() => child)
      .build();

    expect(() => aggregate.construct()).toThrow(/already owned/);
    expect(composite.snapshot()).toEqual([child]);
    expect(aggregate.component1).toBeNull();
  });

  it("does not allow a mutable container to transfer a fixed aggregate slot", () => {
    const hub = makeHub();
    const child = makeChild(hub, "child");
    const aggregate = AggregateVM1.builder<ComponentVM>()
      .name("aggregate")
      .services(hub, makeDisp())
      .component1(() => child)
      .build();
    aggregate.construct();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    composite.construct();

    expect(() => composite.add(child)).toThrow(/fixed aggregate slot/);
    expect(aggregate.component1).toBe(child);
    expect(composite.snapshot()).toEqual([]);
  });
});
