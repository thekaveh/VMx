// Unit tests for GroupVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/groupVM.test.ts.

import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  ConstructionStatus,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

function makeHub() {
  return new MessageHub();
}
function makeDisp() {
  return RxDispatcher.immediate();
}

describe("GroupVM – lifecycle snapshot iteration", () => {
  it("a child construct hook that mutates the group does not skip siblings", () => {
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [])
      .build();

    const b = ComponentVM.builder().name("b").services(hub, makeDisp()).build();
    const a = ComponentVM.builder()
      .name("a")
      .services(hub, makeDisp())
      .onConstruct(() => {
        group.remove(a);
      })
      .build();
    group.add(a);
    group.add(b);

    group.construct();

    expect(b.status).toBe(ConstructionStatus.Constructed);
  });
});

describe("GroupVM – insert bounds", () => {
  it("throws RangeError out of bounds (length appends)", () => {
    // splice would silently normalize/clamp while the emitted newIndex
    // carried the raw argument (spec/21 §3.2).
    const hub = makeHub();
    const group = GroupVM.builder<ComponentVM>()
      .name("g")
      .services(hub, makeDisp())
      .children(() => [])
      .build();
    group.construct();

    const a = ComponentVM.builder().name("a").services(hub, makeDisp()).build();
    group.insert(0, a);
    expect(group.count).toBe(1);
    const b = ComponentVM.builder().name("b").services(hub, makeDisp()).build();
    expect(() => group.insert(-1, b)).toThrow(RangeError);
    expect(() => group.insert(3, b)).toThrow(RangeError);
  });
});
