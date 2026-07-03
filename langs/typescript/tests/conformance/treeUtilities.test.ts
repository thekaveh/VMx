import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVM,
  CompositeVM,
  AggregateVM2,
  AggregateVM3,
  AggregateVM6,
  ComponentVMBase,
  ViewModelType,
  walk,
  find,
} from "../../src/index.js";
import type { IDispatcher } from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }
function makeChild(hub: MessageHub, name: string) {
  return ComponentVM.builder().name(name).services(hub, makeDisp()).build();
}

// ---------------------------------------------------------------------------
// UTIL-001
// ---------------------------------------------------------------------------

describe("UTIL-001", () => {
  it("walk yields root then descendants in DFS pre-order", () => {
    const hub = makeHub();
    const disp = makeDisp();

    const leaf1 = makeChild(hub, "leaf1");
    const leaf2 = makeChild(hub, "leaf2");
    const leaf3 = makeChild(hub, "leaf3");

    const inner = CompositeVM.builder<ComponentVM>()
      .name("inner")
      .services(hub, disp)
      .children(() => [leaf1, leaf2])
      .build();
    inner.construct();

    const root = CompositeVM.builder<ComponentVM>()
      .name("root")
      .services(hub, disp)
      .children(() => [inner, leaf3])
      .build();
    root.construct();

    const visited: string[] = [];
    for (const node of walk(root)) {
      visited.push(node.name);
    }

    // DFS pre-order: root → inner → leaf1 → leaf2 → leaf3
    expect(visited).toEqual(["root", "inner", "leaf1", "leaf2", "leaf3"]);
  });
});

// ---------------------------------------------------------------------------
// UTIL-002
// ---------------------------------------------------------------------------

describe("UTIL-002", () => {
  it("walk skips empty aggregate slots", () => {
    const hub = makeHub();
    const disp = makeDisp();

    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const c3 = makeChild(hub, "c3");
    // TS aggregate slots are truly-private (#componentN) and `_onConstruct` fills
    // every slot non-optionally, so — unlike Python's settable `_component2` — a
    // single null *middle* slot cannot be forced from a test. Before `construct()`
    // ALL slots are null, which exercises the same declaration-order null-filter
    // (`_children` skips null slots) the catalog scenario targets.
    const agg = AggregateVM3.builder<ComponentVM, ComponentVM, ComponentVM>()
      .name("agg")
      .services(hub, disp)
      .component1(() => c1)
      .component2(() => c2)
      .component3(() => c3)
      .build();

    // Pre-construct: all three slots are null → walk skips them and yields only
    // the aggregate (no undefined/null entries).
    expect([...walk(agg)].map((n) => n.name)).toEqual(["agg"]);

    // Post-construct: every populated slot is reachable in declaration order.
    agg.construct();
    expect([...walk(agg)].map((n) => n.name)).toEqual(["agg", "c1", "c2", "c3"]);
  });
});

// ---------------------------------------------------------------------------
// UTIL-002 (AggregateVM6 reachability)
// ---------------------------------------------------------------------------

describe("UTIL-002 (AggregateVM6 reachability)", () => {
  it("walk visits component_6 slot on AggregateVM6", () => {
    const hub = makeHub();
    const disp = makeDisp();

    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const c3 = makeChild(hub, "c3");
    const c4 = makeChild(hub, "c4");
    const c5 = makeChild(hub, "c5");
    const c6 = makeChild(hub, "c6");

    const agg = AggregateVM6.builder<
      ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
    >()
      .name("agg6")
      .services(hub, disp)
      .component1(() => c1)
      .component2(() => c2)
      .component3(() => c3)
      .component4(() => c4)
      .component5(() => c5)
      .component6(() => c6)
      .build();
    agg.construct();

    const visited: string[] = [];
    for (const node of walk(agg)) visited.push(node.name);

    expect(visited).toEqual(["agg6", "c1", "c2", "c3", "c4", "c5", "c6"]);
  });
});

// ---------------------------------------------------------------------------
// UTIL-003
// ---------------------------------------------------------------------------

describe("UTIL-003", () => {
  it("find returns first matching node and short-circuits", () => {
    const hub = makeHub();
    const disp = makeDisp();

    const c1 = makeChild(hub, "c1");
    const c2 = makeChild(hub, "c2");
    const c3 = makeChild(hub, "c3");

    const agg = AggregateVM2.builder<ComponentVM, ComponentVM>()
      .name("agg")
      .services(hub, disp)
      .component1(() => c1)
      .component2(() => c2)
      .build();
    agg.construct();

    const root = CompositeVM.builder<ComponentVMBase>()
      .name("root")
      .services(hub, disp)
      .children(() => [agg, c3])
      .build();
    root.construct();

    const visited: string[] = [];
    const result = find(root, (vm) => {
      visited.push(vm.name);
      return vm.name === "c2";
    });
    expect(result).toBe(c2);
    // Short-circuits: the predicate is not invoked after the first match, so
    // c3 (traversed after the matched c2) is never visited and c2 is the last
    // predicate call — matches the Python/C# UTIL-003 visited-order assertion.
    expect(visited[visited.length - 1]).toBe("c2");
    expect(visited).not.toContain("c3");

    // When nothing matches, returns null.
    const missing = find(root, (vm) => vm.name === "ghost");
    expect(missing).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// VMX-023 — arity-independent aggregate traversal via the typed components()
// accessor (no `component${i}` slot-name reflection bounded at 6).
// ---------------------------------------------------------------------------

class _Arity7Aggregate extends ComponentVMBase {
  readonly #slots: readonly ComponentVMBase[];
  constructor(opts: {
    name: string;
    hub: MessageHub;
    dispatcher: IDispatcher;
    slots: readonly ComponentVMBase[];
  }) {
    super({
      name: opts.name,
      hint: "",
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#slots = opts.slots;
  }
  get type(): ViewModelType {
    return ViewModelType.Aggregate;
  }
  components(): readonly ComponentVMBase[] {
    return this.#slots;
  }
}

describe("VMX-023", () => {
  it("walk descends into aggregate slots via components() even beyond arity 6", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const slots = Array.from({ length: 7 }, (_, i) =>
      makeChild(hub, `c${String(i + 1)}`),
    );
    const agg = new _Arity7Aggregate({
      name: "agg7",
      hub,
      dispatcher: disp,
      slots,
    });

    // The old reflection (`component${i}` for i=1..6) would have silently
    // dropped the seventh slot; the typed accessor yields all of them.
    const visited = [...walk(agg)].map((vm) => vm.name);
    expect(visited).toEqual([
      "agg7",
      "c1",
      "c2",
      "c3",
      "c4",
      "c5",
      "c6",
      "c7",
    ]);
  });
});
