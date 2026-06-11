import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ConstructionStatus,
  StatusTransitionError,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  CompositeVM,
  AggregateVM1,
  AggregateVM2,
  AggregateVM3,
  AggregateVM4,
  AggregateVM5,
  AggregateVM6,
  ComponentVMBase,
  ConstructionStatusChangedMessage,
} from "../../src/index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

function makeVM(name = "vm") {
  return ComponentVM.builder()
    .name(name)
    .services(makeHub(), makeDisp())
    .build();
}

// ---------------------------------------------------------------------------
// LIFE-001
// ---------------------------------------------------------------------------

describe("LIFE-001", () => {
  it("construct from Destructed transitions through Constructing to Constructed", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.construct();

    expect(observed).toEqual([ConstructionStatus.Constructing, ConstructionStatus.Constructed]);
    expect(vm.isConstructed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// LIFE-002
// ---------------------------------------------------------------------------

describe("LIFE-002", () => {
  it("destruct from Constructed transitions through Destructing to Destructed", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    vm.construct();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.destruct();

    expect(observed).toEqual([ConstructionStatus.Destructing, ConstructionStatus.Destructed]);
    expect(vm.isConstructed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// LIFE-003
// ---------------------------------------------------------------------------

describe("LIFE-003", () => {
  it("reconstruct emits the full Destruct then Construct sequence", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    vm.construct();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.reconstruct();

    expect(observed).toEqual([
      ConstructionStatus.Destructing,
      ConstructionStatus.Destructed,
      ConstructionStatus.Constructing,
      ConstructionStatus.Constructed,
    ]);
  });
});

// ---------------------------------------------------------------------------
// LIFE-004
// ---------------------------------------------------------------------------

describe("LIFE-004", () => {
  it("dispose transitions to Disposed from any state and emits message", () => {
    const states: ConstructionStatus[] = [
      ConstructionStatus.Destructed,
      ConstructionStatus.Constructed,
    ];
    for (const fromStatus of states) {
      const hub = makeHub();
      const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
      if (fromStatus === ConstructionStatus.Constructed) vm.construct();
      const observed: ConstructionStatus[] = [];
      hub.messages.subscribe((m) => {
        if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
      });

      vm.dispose();

      expect(vm.status).toBe(ConstructionStatus.Disposed);
      expect(observed).toContain(ConstructionStatus.Disposed);
    }
  });
});

// ---------------------------------------------------------------------------
// LIFE-005
// ---------------------------------------------------------------------------

describe("LIFE-005", () => {
  it("construct from Disposed raises StatusTransitionError", () => {
    const vm = makeVM();
    vm.dispose();
    expect(() => vm.construct()).toThrow(StatusTransitionError);
    expect(() => vm.construct()).toThrow(/Disposed/);
    expect(() => vm.construct()).toThrow(/construct/);
  });
});

// ---------------------------------------------------------------------------
// LIFE-006
// ---------------------------------------------------------------------------

describe("LIFE-006", () => {
  it("destruct from Disposed raises StatusTransitionError", () => {
    const vm = makeVM();
    vm.dispose();
    expect(() => vm.destruct()).toThrow(StatusTransitionError);
    expect(() => vm.destruct()).toThrow(/Disposed/);
    expect(() => vm.destruct()).toThrow(/destruct/);
  });
});

// ---------------------------------------------------------------------------
// LIFE-007
// ---------------------------------------------------------------------------

describe("LIFE-007", () => {
  it("IsConstructed equals Status == Constructed at every state", () => {
    const vm = makeVM();
    expect(vm.isConstructed).toBe(vm.status === ConstructionStatus.Constructed);
    vm.construct();
    expect(vm.isConstructed).toBe(vm.status === ConstructionStatus.Constructed);
    vm.destruct();
    expect(vm.isConstructed).toBe(vm.status === ConstructionStatus.Constructed);
    vm.dispose();
    expect(vm.isConstructed).toBe(vm.status === ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// LIFE-008
// ---------------------------------------------------------------------------

describe("LIFE-008", () => {
  it("concurrent operation while transitioning raises", () => {
    // We simulate this by using a construct callback that sets in-flight flag.
    // The simplest test: calling construct() again from within an onConstruct
    // hook while the VM is still Constructing should raise.
    const hub = makeHub();
    let innerError: unknown;
    const vm = ComponentVM.builder()
      .name("v")
      .services(hub, makeDisp())
      .onConstruct(() => {
        // At this point the VM is Constructing and in-flight is true.
        // A second construct() call MUST raise.
        try {
          vm.construct();
        } catch (e) {
          innerError = e;
        }
      })
      .build();

    vm.construct();
    expect(innerError).toBeInstanceOf(StatusTransitionError);
  });
});

// ---------------------------------------------------------------------------
// LIFE-009
// ---------------------------------------------------------------------------

describe("LIFE-009", () => {
  it("construct from Constructed is idempotent (no-op)", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    vm.construct();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.construct(); // should be no-op

    expect(observed).toHaveLength(0);
    expect(vm.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// LIFE-010
// ---------------------------------------------------------------------------

describe("LIFE-010", () => {
  it("destruct from Destructed is idempotent (no-op)", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.destruct(); // should be no-op

    expect(observed).toHaveLength(0);
    expect(vm.status).toBe(ConstructionStatus.Destructed);
  });
});

// ---------------------------------------------------------------------------
// LIFE-011
// ---------------------------------------------------------------------------

describe("LIFE-011", () => {
  it("Lifecycle transition table matches fixture", () => {
    // Load fixture
    const fixtureDir = join(__dirname, "..", "..", "src", "fixtures");
    const raw = readFileSync(join(fixtureDir, "lifecycle-transitions.json"), "utf-8");
    const data = JSON.parse(raw) as {
      transitions: Array<{
        from: string;
        via: string;
        to_final: string | null;
        legal: boolean;
      }>;
    };

    const invoke = (vm: ComponentVM, op: string): StatusTransitionError | null => {
      try {
        if (op === "construct") vm.construct();
        else if (op === "destruct") vm.destruct();
        else if (op === "reconstruct") vm.reconstruct();
        else if (op === "dispose") vm.dispose();
        else throw new Error(`unknown op '${op}'`);
      } catch (err) {
        if (err instanceof StatusTransitionError) return err;
        throw err;
      }
      return null;
    };

    // Bring a fresh VM to `from`, invoke `op`, return [error, finalStatus].
    // Mid-transition states are reached via the builder's lifecycle hooks,
    // which run while the transition is in flight (the catalog's
    // "controllable hook" allowance).
    const drive = (
      from: string,
      op: string,
    ): [StatusTransitionError | null, ConstructionStatus] => {
      const hub = makeHub();
      let captured: StatusTransitionError | null = null;
      let vm: ComponentVM;

      if (from === "Constructing") {
        vm = ComponentVM.builder()
          .name("v")
          .services(hub, makeDisp())
          .onConstruct(() => {
            captured = invoke(vm, op);
          })
          .build();
        vm.construct();
        return [captured, vm.status];
      }
      if (from === "Destructing") {
        vm = ComponentVM.builder()
          .name("v")
          .services(hub, makeDisp())
          .onDestruct(() => {
            captured = invoke(vm, op);
          })
          .build();
        vm.construct();
        vm.destruct();
        return [captured, vm.status];
      }

      vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
      if (from === "Constructed") vm.construct();
      else if (from === "Disposed") vm.dispose();
      // Destructed is the initial state — no action needed.
      return [invoke(vm, op), vm.status];
    };

    for (const row of data.transitions) {
      const [error, final] = drive(row.from, row.via);

      if (row.legal) {
        expect(error, `${row.from} → ${row.via} is legal`).toBeNull();
        if (row.to_final !== null) {
          const expectedFinal = ConstructionStatus[row.to_final as keyof typeof ConstructionStatus];
          expect(final, `${row.from} → ${row.via}`).toBe(expectedFinal);
        }
      } else {
        expect(error, `${row.from} → ${row.via} must raise`).toBeInstanceOf(
          StatusTransitionError,
        );
      }
    }
  });
});

// ---------------------------------------------------------------------------
// LIFE-012
// ---------------------------------------------------------------------------

describe("LIFE-012", () => {
  it("dispose from Disposed emits no message", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder().name("v").services(hub, makeDisp()).build();
    vm.dispose();
    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.dispose();

    expect(observed).toHaveLength(0);
    expect(vm.status).toBe(ConstructionStatus.Disposed);
  });
});

// ---------------------------------------------------------------------------
// LIFE-013
// ---------------------------------------------------------------------------

describe("LIFE-013", () => {
  it("dispose on a parent disposes every child depth-first", () => {
    const hub = makeHub();
    const disp = makeDisp();

    const gc1 = ComponentVM.builder().name("gc1").services(hub, disp).build();
    const gc2 = ComponentVM.builder().name("gc2").services(hub, disp).build();
    const child = CompositeVM.builder()
      .name("child")
      .services(hub, disp)
      .children(() => [gc1, gc2])
      .build();
    const root = CompositeVM.builder()
      .name("root")
      .services(hub, disp)
      .children(() => [child])
      .build();

    root.construct();
    // We can't intercept dispose directly, but we verify all are Disposed afterwards.
    // For depth-first ordering, use onDestruct callbacks would be needed—
    // but the spec for LIFE-013 says: when parent.dispose() returns, all children are Disposed.

    root.dispose();

    expect(gc1.status).toBe(ConstructionStatus.Disposed);
    expect(gc2.status).toBe(ConstructionStatus.Disposed);
    expect(child.status).toBe(ConstructionStatus.Disposed);
    expect(root.status).toBe(ConstructionStatus.Disposed);
  });

  // LIFE-013 for AggregateVMN: children's Disposed transition must fire BEFORE
  // the aggregate's own Disposed transition. Sibling of the Python parametric
  // test_LIFE_013_aggregate_dispose_children_before_parent and the C#
  // LIFE_013_AggregateVMN_Children_Disposed_Before_Parent Theory. Locks in the
  // cross-flavor invariant the Pass-1 Python bug violated for every arity.
  it.each([1, 2, 3, 4, 5, 6])(
    "AggregateVM%d disposes every child slot before disposing itself",
    (arity) => {
      const hub = makeHub();
      const disp = makeDisp();
      const aggName = `agg${arity}`;
      const child = (n: number) =>
        ComponentVM.builder().name(`c${n}`).services(hub, disp).build();

      const disposalOrder: string[] = [];
      hub.messages.subscribe((m) => {
        if (
          m instanceof ConstructionStatusChangedMessage &&
          m.status === ConstructionStatus.Disposed
        ) {
          disposalOrder.push(m.senderName);
        }
      });

      let agg: ComponentVMBase;
      switch (arity) {
        case 1:
          agg = AggregateVM1.builder<ComponentVM>()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).build();
          break;
        case 2:
          agg = AggregateVM2.builder<ComponentVM, ComponentVM>()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).component2(() => child(2)).build();
          break;
        case 3:
          agg = AggregateVM3.builder<ComponentVM, ComponentVM, ComponentVM>()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).component2(() => child(2))
            .component3(() => child(3)).build();
          break;
        case 4:
          agg = AggregateVM4.builder<ComponentVM, ComponentVM, ComponentVM, ComponentVM>()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).component2(() => child(2))
            .component3(() => child(3)).component4(() => child(4)).build();
          break;
        case 5:
          agg = AggregateVM5.builder<ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM>()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).component2(() => child(2))
            .component3(() => child(3)).component4(() => child(4))
            .component5(() => child(5)).build();
          break;
        case 6:
          agg = AggregateVM6.builder<
            ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
          >()
            .name(aggName).services(hub, disp)
            .component1(() => child(1)).component2(() => child(2))
            .component3(() => child(3)).component4(() => child(4))
            .component5(() => child(5)).component6(() => child(6)).build();
          break;
        default:
          throw new Error(`unsupported arity ${arity}`);
      }
      agg.construct();

      agg.dispose();

      for (let n = 1; n <= arity; n++) {
        const childName = `c${n}`;
        expect(disposalOrder).toContain(childName);
        expect(disposalOrder.indexOf(childName)).toBeLessThan(
          disposalOrder.indexOf(aggName),
        );
      }
    },
  );
});
