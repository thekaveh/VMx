import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  ViewModelType,
} from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

// ---------------------------------------------------------------------------
// BLD-001
// ---------------------------------------------------------------------------

describe("BLD-001", () => {
  it("Setter returns a new builder instance", () => {
    const b1 = ComponentVM.builder();
    const b2 = b1.name("x");

    expect(b1).not.toBe(b2);
    // b1 should not have the name set; b2 should.
    // We verify indirectly: b1.build() should throw (no name set), b2 with services should work.
    const hub = makeHub();
    const disp = makeDisp();
    expect(() => b1.services(hub, disp).build()).toThrow(/name/);
    expect(() => b2.services(hub, disp).build()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// BLD-002
// ---------------------------------------------------------------------------

describe("BLD-002", () => {
  it("Required fields validated on Build", () => {
    // Missing name
    const hub = makeHub();
    const disp = makeDisp();
    expect(() =>
      ComponentVM.builder().services(hub, disp).build()
    ).toThrow(/name/);

    // Missing services
    expect(() =>
      ComponentVM.builder().name("x").build()
    ).toThrow(/services/);

    // Missing model for ComponentVMOf
    expect(() =>
      ComponentVMOf.builder<string>().name("x").services(hub, disp).build()
    ).toThrow(/model/);
  });
});

// ---------------------------------------------------------------------------
// BLD-003
// ---------------------------------------------------------------------------

describe("BLD-003", () => {
  it("Repeated identical Build calls produce equivalent VMs", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const builder = ComponentVM.builder().name("v").hint("h").services(hub, disp);

    const vmA = builder.build();
    const vmB = builder.build();

    expect(vmA).not.toBe(vmB);
    expect(vmA.name).toBe(vmB.name);
    expect(vmA.hint).toBe(vmB.hint);
    expect(vmA.type).toBe(vmB.type);
  });
});

// ---------------------------------------------------------------------------
// BLD-004
// ---------------------------------------------------------------------------

describe("BLD-004", () => {
  it("Field defaults applied when not set", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm = ComponentVM.builder().name("v").services(hub, disp).build();

    expect(vm.hint).toBe("");
    expect(vm.type).toBe(ViewModelType.Component);
    expect(vm.isCurrent).toBe(false);
  });
});
