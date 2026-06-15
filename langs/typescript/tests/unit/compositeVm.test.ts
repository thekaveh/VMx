// Unit tests for CompositeVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/compositeVM.test.ts.

import { describe, expect, it } from "vitest";
import { ComponentVM, CompositeVM, MessageHub, RxDispatcher } from "../../src/index.js";

function makeHub() {
  return new MessageHub();
}
function makeDisp() {
  return RxDispatcher.immediate();
}
function makeChild(hub: MessageHub, name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, makeDisp()).build();
}

describe("CompositeVM – clear()", () => {
  it("routes through _setCurrent so the old current child is deselected", () => {
    const hub = makeHub();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    composite.construct();

    const child = makeChild(hub, "child");
    composite.add(child);
    child.construct();
    composite.current = child;
    expect(child.isCurrent).toBe(true);

    composite.clear();

    expect(composite.current).toBeNull();
    expect(child.isCurrent).toBe(false);
  });
});

describe("CompositeVM – insert bounds", () => {
  it("throws RangeError out of bounds (length appends)", () => {
    // splice would silently normalize/clamp while the emitted newIndex
    // carried the raw argument (spec/21 §3.2).
    const hub = makeHub();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("c")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    composite.construct();

    composite.insert(0, makeChild(hub, "a"));
    expect(composite.count).toBe(1);
    expect(() => composite.insert(-1, makeChild(hub, "b"))).toThrow(RangeError);
    expect(() => composite.insert(3, makeChild(hub, "c2"))).toThrow(RangeError);
  });
});

// ---------------------------------------------------------------------------
// CompositeVMBuilder.current(selector) — ADR-0042, spec/06 §3.2
// ---------------------------------------------------------------------------

describe("CompositeVMBuilder.current(selector)", () => {
  it("drives initial selection after construct", () => {
    const hub = makeHub();
    const children = ["a", "b", "c"].map((n) => makeChild(hub, n));

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => children)
      .current((xs) => [...xs][1] ?? null)
      .build();
    composite.construct();

    expect(composite.current).toBe(children[1]);
  });

  it("returning null leaves current null", () => {
    const hub = makeHub();
    const children = [makeChild(hub, "a")];

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => children)
      .current(() => null)
      .build();
    composite.construct();

    expect(composite.current).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// CompositeVMBuilder.onCurrentChanged(callback) — ADR-0042, spec/06 §3.2
// ---------------------------------------------------------------------------

describe("CompositeVMBuilder.onCurrentChanged(callback)", () => {
  it("fires after each current change", () => {
    const hub = makeHub();
    const children = ["a", "b"].map((n) => makeChild(hub, n));
    const observed: (ComponentVM | null)[] = [];

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => children)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    composite.construct();
    composite.selectComponent(children[1]!);
    composite.deselectComponent(children[1]!);

    expect(observed).toEqual([children[1], null]);
  });

  it("fires once for initial selector", () => {
    const hub = makeHub();
    const children = [makeChild(hub, "a")];
    const observed: (ComponentVM | null)[] = [];

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, makeDisp())
      .children(() => children)
      .current((xs) => [...xs][0] ?? null)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    composite.construct();

    expect(observed).toEqual([children[0]]);
  });

  it("does not fire when selector returns null or out-of-set (ADR-0042 §5.4)", () => {
    const hub = makeHub();
    const children = [makeChild(hub, "a")];
    const observed: (ComponentVM | null)[] = [];

    // Case 1: selector returns null
    const c1 = CompositeVM.builder<ComponentVM>()
      .name("c-null")
      .services(hub, makeDisp())
      .children(() => children)
      .current(() => null)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    c1.construct();
    expect(observed).toEqual([]);

    // Case 2: selector returns out-of-set
    const foreign = makeChild(hub, "foreign");
    const otherChildren = [makeChild(hub, "a2")];
    const c2 = CompositeVM.builder<ComponentVM>()
      .name("c-foreign")
      .services(hub, makeDisp())
      .children(() => otherChildren)
      .current(() => foreign)
      .onCurrentChanged((vm) => observed.push(vm))
      .build();
    c2.construct();
    expect(observed).toEqual([]);
  });
});
