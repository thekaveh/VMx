import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVM,
  CompositeVM,
  AggregateVM2,
  AggregateVM1,
  AggregateVM6,
  ComponentVMBase,
  walk,
  find,
} from "../../src/index.js";

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
    // AggregateVM1 has only one slot; no component2..5 populated.
    const agg = AggregateVM1.builder<ComponentVM>()
      .name("agg")
      .services(hub, disp)
      .component1(() => c1)
      .build();
    agg.construct();

    const visited: string[] = [];
    for (const node of walk(agg)) {
      visited.push(node.name);
    }

    // Only agg + c1, no undefined/null slots.
    expect(visited).toEqual(["agg", "c1"]);
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

    const result = find(root, (vm) => vm.name === "c2");
    expect(result).toBe(c2);

    // When nothing matches, returns null.
    const missing = find(root, (vm) => vm.name === "ghost");
    expect(missing).toBeNull();
  });
});
