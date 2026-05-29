import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  CompositeVM,
  ComponentVM,
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

    expect(fwd.name).toBe(inner.name);
    expect(fwd.hint).toBe(inner.hint);
    expect(fwd.type).toBe(inner.type);
    expect(fwd.status).toBe(inner.status);
    expect(fwd.isConstructed).toBe(inner.isConstructed);
    expect(fwd.isCurrent).toBe(inner.isCurrent);
    expect(fwd.model).toBe(inner.model);

    fwd.construct();
    expect(inner.isConstructed).toBe(true);
    expect(fwd.isConstructed).toBe(true);
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

    expect(fwd.hint).toBe("OVERRIDE");
    expect(fwd.name).toBe("inner"); // other members still delegate
    expect(fwd.model).toBe("m");
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
