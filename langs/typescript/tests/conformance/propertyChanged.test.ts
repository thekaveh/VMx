import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  PropertyChangedMessage,
} from "../../src/index.js";

interface TestModel {
  id: number;
  name: string;
}

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

function makeModeled(hub: MessageHub, model: TestModel) {
  return ComponentVMOf.builder<TestModel>()
    .name("vm1")
    .model(model)
    .services(hub, makeDisp())
    .build();
}

// ---------------------------------------------------------------------------
// PROP-001
// ---------------------------------------------------------------------------

describe("PROP-001", () => {
  it("Setting a property to a different value publishes PropertyChangedMessage", () => {
    const hub = makeHub();
    const m1: TestModel = { id: 1, name: "Alice" };
    const m2: TestModel = { id: 2, name: "Bob" };
    const vm = makeModeled(hub, m1);

    const received: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((msg) => {
      if (msg instanceof PropertyChangedMessage) received.push(msg);
    });

    vm.model = m2;

    // Spec PROP-001: the subscriber observes exactly one PropertyChangedMessage
    // for "model" (a duplicate-emission regression must fail here).
    const modelMsgs = received.filter((m) => m.propertyName === "model");
    expect(modelMsgs, "exactly one PropertyChangedMessage for 'model'").toHaveLength(1);
    expect(modelMsgs[0]!.sender).toBe(vm);
  });
});

// ---------------------------------------------------------------------------
// PROP-002
// ---------------------------------------------------------------------------

describe("PROP-002", () => {
  it("Setting a property to the same value does NOT publish", () => {
    const hub = makeHub();
    const m1: TestModel = { id: 1, name: "Alice" };
    const vm = makeModeled(hub, m1);

    const received: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((msg) => {
      if (msg instanceof PropertyChangedMessage) received.push(msg);
    });

    vm.model = m1; // same reference

    expect(received.filter((m) => m.propertyName === "model")).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// PROP-003
// ---------------------------------------------------------------------------

describe("PROP-003", () => {
  it("Sender identity equals the VM instance", () => {
    const hub = makeHub();
    const m1: TestModel = { id: 1, name: "Alice" };
    const m2: TestModel = { id: 2, name: "Bob" };
    const vm = makeModeled(hub, m1);

    let senderVM: unknown;
    hub.messages.subscribe((msg) => {
      if (msg instanceof PropertyChangedMessage && msg.propertyName === "model") {
        senderVM = msg.sender;
      }
    });

    vm.model = m2;

    expect(senderVM).toBe(vm);
  });
});

// ---------------------------------------------------------------------------
// PROP-004
// ---------------------------------------------------------------------------

describe("PROP-004", () => {
  it("PropertyName equals the property name and SenderName equals VM name", () => {
    const hub = makeHub();
    const m1: TestModel = { id: 1, name: "Alice" };
    const m2: TestModel = { id: 2, name: "Bob" };
    const vm = makeModeled(hub, m1);

    let propertyName: string | undefined;
    let senderName: string | undefined;
    hub.messages.subscribe((msg) => {
      if (msg instanceof PropertyChangedMessage && msg.propertyName === "model") {
        propertyName = msg.propertyName;
        senderName = msg.senderName;
      }
    });

    vm.model = m2;

    expect(propertyName).toBe("model");
    expect(senderName).toBe("vm1");
  });
});
