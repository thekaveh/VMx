import { describe, expect, it } from "vitest";

import { ComponentVMBase } from "../../src/components/componentVMBase.js";
import { ViewModelType } from "../../src/components/types.js";
import { ConstructionStatusChangedMessage } from "../../src/messages/constructionStatusChanged.js";
import { MessageHub } from "../../src/services/messageHub.js";
import { RxDispatcher } from "../../src/services/dispatcher.js";

type Resource =
  | (() => void)
  | { dispose(): void }
  | { unsubscribe(): void };

class ProbeVM extends ComponentVMBase {
  readonly #disposeHook: (() => void) | undefined;

  constructor(hub: MessageHub, disposeHook?: () => void) {
    super({ name: "probe", hint: "", hub, dispatcher: RxDispatcher.immediate() });
    this.#disposeHook = disposeHook;
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  register<T extends Resource>(resource: T): T {
    return this.own(resource);
  }

  protected override _onDispose(): void {
    this.#disposeHook?.();
  }
}

describe("DISP-007", () => {
  it("cleans owned resource shapes in LIFO order", () => {
    const trace: string[] = [];
    const vm = new ProbeVM(new MessageHub(), () => trace.push("hook"));
    vm.register(() => trace.push("function"));
    vm.register({ dispose: () => trace.push("dispose") });
    vm.register({ unsubscribe: () => trace.push("unsubscribe") });

    vm.dispose();

    expect(trace).toEqual(["hook", "unsubscribe", "dispose", "function"]);
  });
});

describe("DISP-008", () => {
  it("cleans each owned resource once across repeated dispose", () => {
    let calls = 0;
    const vm = new ProbeVM(new MessageHub());
    vm.register(() => (calls += 1));
    vm.dispose();
    vm.dispose();
    expect(calls).toBe(1);
  });
});

describe("DISP-009", () => {
  it("swallows one cleanup failure and continues", () => {
    const trace: string[] = [];
    const vm = new ProbeVM(new MessageHub());
    vm.register(() => trace.push("first"));
    vm.register(() => {
      throw new Error("boom");
    });
    vm.register(() => trace.push("last"));

    expect(() => vm.dispose()).not.toThrow();
    expect(trace).toEqual(["last", "first"]);
  });
});

describe("DISP-010", () => {
  it("cleans registration after disposal immediately once", () => {
    let calls = 0;
    const vm = new ProbeVM(new MessageHub());
    vm.dispose();
    vm.register(() => (calls += 1));
    vm.dispose();
    expect(calls).toBe(1);
  });
});

describe("DISP-011", () => {
  it("keeps owned resources across reconstruct until final disposal", () => {
    let calls = 0;
    const vm = new ProbeVM(new MessageHub());
    vm.register(() => (calls += 1));
    vm.construct();
    vm.reconstruct();
    expect(calls).toBe(0);
    vm.dispose();
    expect(calls).toBe(1);
  });
});

describe("DISP-012", () => {
  it("exposes the injected hub publicly and read-only", () => {
    const hub = new MessageHub();
    const vm = new ProbeVM(hub);
    expect(vm.hub).toBe(hub);
  });
});

describe("DISP-013", () => {
  it("does not dispose the shared injected hub", () => {
    const hub = new MessageHub();
    const vm = new ProbeVM(hub);
    let received = 0;
    hub.messages.subscribe(() => (received += 1));
    vm.dispose();
    const baseline = received;

    hub.send(ConstructionStatusChangedMessage.create(vm, vm.name, vm.status));

    expect(received).toBe(baseline + 1);
  });
});
