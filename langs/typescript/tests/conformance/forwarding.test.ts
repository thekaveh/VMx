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

  it("forwards the model setter write-through to the wrapped VM", () => {
    const hub = makeHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("before")
      .services(hub, makeDisp())
      .build();

    class NoopForwarding extends ForwardingComponentVM<string> {
      constructor() {
        super(inner);
      }
    }
    const fwd = new NoopForwarding();

    // Setting the decorator's model delegates to the wrapped instance
    // (spec/09-forwarding.md §1: the modeled component's model is settable and
    // the decorator forwards every member). Parity with C#/Python/Swift.
    fwd.model = "after";
    expect(inner.model).toBe("after");
    expect(fwd.model).toBe("after");
  });

  it("forwards hub, property stream, model publication, and selection", () => {
    const hub = makeHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("model")
      .services(hub, makeDisp())
      .build();
    const parent = CompositeVM.builder<ComponentVMOf<string>>()
      .name("parent")
      .services(hub, makeDisp())
      .children(() => [inner])
      .build();
    parent.construct();
    const fwd = new ForwardingComponentVM(inner);
    const changes: string[] = [];
    const subscription = fwd.propertyChanged.subscribe((name) => changes.push(name));

    expect(fwd.hub).toBe(hub);
    fwd.republishModel();
    fwd.select();
    expect(inner.isCurrent).toBe(true);
    fwd.deselect();
    expect(inner.isCurrent).toBe(false);
    expect(changes).toContain("model");
    subscription.unsubscribe();
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

  it("ForwardingCompositeVM delegates the complete composite surface", () => {
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
    const fwd = new ForwardingCompositeVM(composite);
    let membershipChanges = 0;
    const membership = fwd.subscribeMembership(() => { membershipChanges++; });

    expect(fwd.hub).toBe(hub);
    expect(fwd.supportsChildSelection).toBe(true);
    expect(fwd.currentChild).toBeNull();
    expect(fwd.snapshot()).toEqual([vm1, vm2]);
    expect(fwd.canSelectComponent(vm1)).toBe(true);
    fwd.selectComponent(vm1);
    expect(fwd.current).toBe(vm1);
    fwd.current = vm2;
    expect(composite.current).toBe(vm2);
    fwd.deselectComponent(vm2);
    expect(fwd.current).toBeNull();
    fwd.selectChild(vm1);
    expect(fwd.currentChild).toBe(vm1);
    fwd.deselectChild(vm1);
    expect(fwd.currentChild).toBeNull();
    fwd.move(0, 1);
    expect(fwd.snapshot()).toEqual([vm2, vm1]);
    expect(membershipChanges).toBe(1);
    membership.unsubscribe();
  });
});
