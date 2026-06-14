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
// CompositeVMBuilder.current(selector) — ADR-0042, spec/06 §3.X
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
