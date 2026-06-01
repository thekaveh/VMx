import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  ReadonlyComponentVMOf,
  NullMessageHub,
  NullDispatcher,
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

// ---------------------------------------------------------------------------
// BLD-005 — Additive setters retain prior values across repeated calls
// ---------------------------------------------------------------------------

describe("BLD-005", () => {
  it("Triggers is additive — repeated calls retain prior values", async () => {
    const { Subject } = await import("rxjs");
    const { RelayCommand } = await import("../../src/commands/relayCommand.js");

    const trigger1 = new Subject<void>();
    const trigger2 = new Subject<void>();

    const cmd = RelayCommand.builder()
      .triggers(trigger1.asObservable())
      .triggers(trigger2.asObservable())
      .build();

    let firings = 0;
    cmd.canExecuteChanged.subscribe(() => firings++);

    trigger1.next();
    expect(firings).toBe(1);

    trigger2.next();
    expect(firings).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// SV1 — withNullServices() chainable Wither parity (ADR-0035)
// ---------------------------------------------------------------------------

describe("withNullServices() chainable Wither", () => {
  it("wires the null hub + null dispatcher in one call (non-modeled)", () => {
    const vm = ComponentVM.builder().name("v").withNullServices().build();
    // The wired services are private; observe behavior — the VM should
    // build successfully (no BuilderValidationError("services")), and
    // disposing it should not throw.
    expect(vm).toBeDefined();
    vm.dispose();
  });

  it("wires the null hub + null dispatcher in one call (modeled)", () => {
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("init")
      .withNullServices()
      .build();
    expect(vm).toBeDefined();
    vm.dispose();
  });

  it("wires the null hub + null dispatcher in one call (readonly modeled)", () => {
    const vm = ReadonlyComponentVMOf.builder<string>()
      .name("v")
      .model("init")
      .withNullServices()
      .build();
    expect(vm).toBeDefined();
    vm.dispose();
  });

  it("returns a new builder instance (BLD-001 compliance)", () => {
    const b1 = ComponentVMOf.builder<string>().name("v").model("init");
    const b2 = b1.withNullServices();
    expect(b1).not.toBe(b2);
    // b1 still has no services; building without them throws
    expect(() => b1.build()).toThrow(/services/);
    // b2 builds fine
    const vm = b2.build();
    expect(vm).toBeDefined();
    vm.dispose();
  });

  it("equivalent to explicit services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE)", () => {
    const viaWither = ComponentVM.builder().name("v").withNullServices().build();
    const viaExplicit = ComponentVM.builder()
      .name("v")
      .services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE)
      .build();
    // Both VMs should construct successfully and have equivalent surfaces.
    expect(viaWither.name).toBe(viaExplicit.name);
    expect(viaWither.type).toBe(viaExplicit.type);
    viaWither.dispose();
    viaExplicit.dispose();
  });
});
