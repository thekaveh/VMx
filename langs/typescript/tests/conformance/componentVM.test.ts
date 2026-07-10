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
  ComponentVMBase,
  ViewModelType,
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

    // Exactly one PropertyChanged for "model" (catches duplicate emissions).
    expect(received.filter((p) => p === "model")).toHaveLength(1);
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
    // Exactly one PropertyChanged for "modeledHint" (catches duplicate emissions).
    expect(received.filter((p) => p === "modeledHint")).toHaveLength(1);
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

    // Spec CVM-005: neither Name nor Hint exposes a public setter.
    const nameDesc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(vm), "name");
    expect(nameDesc?.set).toBeUndefined();
    const hintDesc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(vm), "hint");
    expect(hintDesc?.set).toBeUndefined();
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

class NotificationProbeVM extends ComponentVMBase {
  #value = 0;

  constructor(hub: MessageHub) {
    super({ name: "probe", hint: "", hub, dispatcher: makeDisp() });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get value(): number {
    return this.#value;
  }

  set value(value: number) {
    if (this.#value === value) return;
    this.#value = value;
    this._notifyPropertyChanged("value");
  }

  emitValueNotification(): void {
    this._notifyPropertyChanged("value");
  }
}

describe("CVM-007", () => {
  it("emits one hub notification before one local notification", () => {
    const hub = makeHub();
    const vm = new NotificationProbeVM(hub);
    const trace: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "value") {
        trace.push(`hub:${String(vm.value)}`);
      }
    });
    vm.propertyChanged.subscribe((name) => trace.push(`local:${name}:${String(vm.value)}`));

    vm.value = 7;

    expect(trace).toEqual(["hub:7", "local:value:7"]);
  });

  it("documents deferred delivery and completes an admitted pair across disposal", () => {
    const batchedHub = makeHub();
    const batchedVm = new NotificationProbeVM(batchedHub);
    const batchedTrace: string[] = [];
    batchedHub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "value") {
        batchedTrace.push("hub");
      }
    });
    batchedVm.propertyChanged.subscribe((name) => {
      if (name === "value") batchedTrace.push("local");
    });

    batchedHub.batch(() => {
      batchedVm.value = 7;
    });

    expect(batchedTrace).toEqual(["local", "hub"]);

    const disposingHub = makeHub();
    const disposingVm = new NotificationProbeVM(disposingHub);
    const disposingTrace: string[] = [];
    disposingHub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "value") {
        disposingTrace.push("hub");
        disposingVm.dispose();
      }
    });
    disposingVm.propertyChanged.subscribe((name) => {
      if (name === "value") disposingTrace.push("local");
    });

    disposingVm.value = 7;

    expect(disposingTrace).toEqual(["hub", "local"]);
  });
});

describe("CVM-008", () => {
  it("leaves equality suppression to the setter", () => {
    const hub = makeHub();
    const vm = new NotificationProbeVM(hub);
    const hubNames: string[] = [];
    const localNames: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) hubNames.push(message.propertyName);
    });
    vm.propertyChanged.subscribe((name) => localNames.push(name));

    vm.value = 7;
    vm.value = 7;

    expect(hubNames).toEqual(["value"]);
    expect(localNames).toEqual(["value"]);
  });
});

describe("CVM-009", () => {
  it("is inert after disposal", () => {
    const hub = makeHub();
    const vm = new NotificationProbeVM(hub);
    const hubNames: string[] = [];
    const localNames: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) hubNames.push(message.propertyName);
    });
    vm.propertyChanged.subscribe((name) => localNames.push(name));
    vm.dispose();
    hubNames.length = 0;
    localNames.length = 0;

    vm.emitValueNotification();

    expect(hubNames).toEqual([]);
    expect(localNames).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// VMX-006 — post-dispose isCurrent change is a silent no-op
// ---------------------------------------------------------------------------

describe("VMX-006", () => {
  it("setting isCurrent after dispose leaks no PropertyChangedMessage", () => {
    const hub = makeHub();
    const disp = makeDisp();
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .build();
    vm.construct();
    vm.dispose();

    const propNames: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) propNames.push(m.propertyName);
    });

    // Internal selection hook the parent normally drives.
    vm._setIsCurrent(true);

    // spec/02 invariant 3 — Disposed is terminal: no PropertyChangedMessage leaks.
    expect(propNames).not.toContain("isCurrent");
    expect(vm.isCurrent).toBe(false);
  });
});
