import { describe, it, expect } from "vitest";
import {
  ConstructionStatus,
  MessageHub,
  RxDispatcher,
  ComponentVM,
  ComponentVMOf,
  ReadonlyComponentVMOf,
  ConstructionStatusChangedMessage,
  PropertyChangedMessage,
  CompositeVM,
} from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

// ---------------------------------------------------------------------------
// CVM-001
// ---------------------------------------------------------------------------

describe("CVM-001", () => {
  it("Construct emits ConstructionStatusChangedMessage(Constructed)", () => {
    const hub = makeHub();
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, makeDisp())
      .build();

    const observed: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) observed.push(m.status);
    });

    vm.construct();

    expect(observed).toEqual([ConstructionStatus.Constructing, ConstructionStatus.Constructed]);
    expect(vm.isConstructed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// CVM-002
// ---------------------------------------------------------------------------

describe("CVM-002", () => {
  it("Modeled component fires PropertyChanged('Model') on set", () => {
    const hub = makeHub();
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m1")
      .services(hub, makeDisp())
      .build();

    const received: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) received.push(m.propertyName);
    });

    vm.model = "m2";

    expect(received).toContain("Model");
  });
});

// ---------------------------------------------------------------------------
// CVM-003
// ---------------------------------------------------------------------------

describe("CVM-003", () => {
  it("ReadonlyComponentVMOf has no Model setter", () => {
    const hub = makeHub();
    const m = "initial-model";
    const vm = ReadonlyComponentVMOf.builder<string>()
      .name("v")
      .model(m)
      .services(hub, makeDisp())
      .build();

    expect(vm.model).toBe(m);
    // TypeScript type system enforces no setter; verify at runtime by checking
    // there is no setter via property descriptor.
    const descriptor = Object.getOwnPropertyDescriptor(
      Object.getPrototypeOf(vm),
      "model",
    );
    expect(descriptor?.set).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// CVM-004
// ---------------------------------------------------------------------------

describe("CVM-004", () => {
  it("ModeledHint recomputes when Model changes", () => {
    const hub = makeHub();
    const vm = ComponentVMOf.builder<{ id: number }>()
      .name("v")
      .model({ id: 7 })
      .modeledHinter((m) => `hint:${m.id}`)
      .services(hub, makeDisp())
      .build();

    const received: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) received.push(m.propertyName);
    });

    vm.model = { id: 8 };

    expect(vm.modeledHint).toBe("hint:8");
    expect(received).toContain("ModeledHint");
  });
});

// ---------------------------------------------------------------------------
// CVM-005
// ---------------------------------------------------------------------------

describe("CVM-005", () => {
  it("Name and Hint are immutable post-construction", () => {
    const hub = makeHub();
    const vm = ComponentVM.builder()
      .name("orig")
      .hint("h")
      .services(hub, makeDisp())
      .build();

    expect(vm.name).toBe("orig");
    expect(vm.hint).toBe("h");

    const nameDesc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(vm), "name");
    expect(nameDesc?.set).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// CVM-006
// ---------------------------------------------------------------------------

describe("CVM-006", () => {
  it("SelectCommand can_execute reflects selection state", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .build();
    const parent = CompositeVM.builder<typeof vm>()
      .name("parent")
      .services(hub, disp)
      .children(() => [vm])
      .build();

    parent.construct();

    // vm is Constructed, parent.current is null → canSelect should be true
    expect(vm.selectCommand.canExecute()).toBe(true);

    vm.select();
    // Now vm is current → canSelect returns false
    expect(vm.selectCommand.canExecute()).toBe(false);
  });
});
