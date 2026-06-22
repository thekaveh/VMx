import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  CompositeVM,
  ComponentVM,
  ConstructionStatus,
  ForwardingComponentVM,
  ForwardingCompositeVM,
} from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

// ---------------------------------------------------------------------------
// FWD-001
// ---------------------------------------------------------------------------

describe("FWD-001", () => {
  it("ForwardingComponentVM delegates every member to wrapped", () => {
    const hub = makeHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .hint("inner-hint")
      .model("inner-model")
      .services(hub, makeDisp())
      .build();

    class NoopForwarding extends ForwardingComponentVM<string> {
      constructor() { super(inner); }
    }

    const fwd = new NoopForwarding();

    // Identity / state / model read-through
    expect(fwd.name).toBe(inner.name);
    expect(fwd.hint).toBe(inner.hint);
    expect(fwd.type).toBe(inner.type);
    expect(fwd.status).toBe(inner.status);
    expect(fwd.isConstructed).toBe(inner.isConstructed);
    expect(fwd.isCurrent).toBe(inner.isCurrent);
    expect(fwd.model).toBe(inner.model);
    expect(fwd.modeledHint).toBe(inner.modeledHint);

    // Command forwarders delegate to the SAME inner command instances
    expect(fwd.selectCommand).toBe(inner.selectCommand);
    expect(fwd.deselectCommand).toBe(inner.deselectCommand);
    expect(fwd.selectNextCommand).toBe(inner.selectNextCommand);
    expect(fwd.selectPreviousCommand).toBe(inner.selectPreviousCommand);
    expect(fwd.reconstructCommand).toBe(inner.reconstructCommand);

    // Lifecycle + selection predicates delegate to the wrapped VM
    expect(fwd.canConstruct()).toBe(inner.canConstruct());
    expect(fwd.canDestruct()).toBe(inner.canDestruct());
    expect(fwd.canReconstruct()).toBe(inner.canReconstruct());
    expect(fwd.canSelect()).toBe(inner.canSelect());
    expect(fwd.canDeselect()).toBe(inner.canDeselect());

    // Lifecycle mutators call through to the wrapped VM, observed via inner
    // state (legal order: construct → reconstruct → destruct → dispose).
    fwd.construct();
    expect(inner.isConstructed).toBe(true);
    expect(fwd.isConstructed).toBe(true);

    fwd.reconstruct();
    expect(inner.status).toBe(ConstructionStatus.Constructed);

    fwd.destruct();
    expect(inner.status).toBe(ConstructionStatus.Destructed);

    fwd.dispose();
    expect(inner.status).toBe(ConstructionStatus.Disposed);
  });
});

// ---------------------------------------------------------------------------
// FWD-002
// ---------------------------------------------------------------------------

describe("FWD-002", () => {
  it("Selective override replaces a single behavior", () => {
    const hub = makeHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .hint("inner-hint")
      .model("m")
      .services(hub, makeDisp())
      .build();

    class OverrideHint extends ForwardingComponentVM<string> {
      constructor() { super(inner); }
      override get hint(): string { return "OVERRIDE"; }
    }

    const fwd = new OverrideHint();

    // Overridden member returns the override value; the wrapped VM is unchanged.
    expect(fwd.hint).toBe("OVERRIDE");
    expect(inner.hint).toBe("inner-hint");

    // All other members still delegate to the wrapped VM unchanged (spec FWD-002).
    expect(fwd.name).toBe(inner.name);
    expect(fwd.type).toBe(inner.type);
    expect(fwd.isConstructed).toBe(inner.isConstructed);
    expect(fwd.status).toBe(inner.status);
    expect(fwd.isCurrent).toBe(inner.isCurrent);
    expect(fwd.model).toBe(inner.model);
    expect(fwd.modeledHint).toBe(inner.modeledHint);

    // Commands still delegate (same instances as the wrapped VM's).
    expect(fwd.selectCommand).toBe(inner.selectCommand);
    expect(fwd.deselectCommand).toBe(inner.deselectCommand);
    expect(fwd.selectNextCommand).toBe(inner.selectNextCommand);
    expect(fwd.selectPreviousCommand).toBe(inner.selectPreviousCommand);
    expect(fwd.reconstructCommand).toBe(inner.reconstructCommand);
  });
});

// ---------------------------------------------------------------------------
// FWD-003
// ---------------------------------------------------------------------------

describe("FWD-003", () => {
  it("ForwardingCompositeVM forwards iteration", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm1 = ComponentVM.builder().name("vm1").services(hub, disp).build();
    const vm2 = ComponentVM.builder().name("vm2").services(hub, disp).build();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => [vm1, vm2])
      .build();
    composite.construct();

    class NoopFwdComposite extends ForwardingCompositeVM<ComponentVM> {
      constructor() { super(composite); }
    }

    const fwd = new NoopFwdComposite();
    const items = [...fwd];

    expect(items).toEqual([vm1, vm2]);
  });

  it("ForwardingCompositeVM forwards setAt to wrapped (parity with C# this[int] setter)", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm1 = ComponentVM.builder().name("vm1").services(hub, disp).build();
    const vm2 = ComponentVM.builder().name("vm2").services(hub, disp).build();
    const vm3 = ComponentVM.builder().name("vm3").services(hub, disp).build();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, disp)
      .children(() => [vm1, vm2])
      .build();
    composite.construct();

    class NoopFwdComposite extends ForwardingCompositeVM<ComponentVM> {
      constructor() { super(composite); }
    }

    const fwd = new NoopFwdComposite();
    fwd.setAt(1, vm3);

    expect([...composite]).toEqual([vm1, vm3]);
  });
});
