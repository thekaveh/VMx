// #726: a throwing background hook rolls back and releases the in-flight
// guard on dispatchers whose foreground and background share one rxjs
// queueScheduler (RxDispatcher.immediate(), NullDispatcher). A throw inside an
// active queueScheduler flush unsubscribes the queued foreground rollback, so
// the rollback must not depend on work queued behind the throwing action.

import { describe, expect, it } from "vitest";
import { TestScheduler } from "rxjs/testing";
import {
  ComponentVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  NullDispatcher,
  RxDispatcher,
  type IDispatcher,
} from "../../src/index.js";

function failingVm(dispatcher: IDispatcher, hub = new MessageHub()) {
  const fail = { construct: true, destruct: false };
  const vm = ComponentVM.builder()
    .name("v")
    .services(hub, dispatcher)
    .background(true)
    .onConstruct(() => {
      if (fail.construct) throw new Error("construct failed");
    })
    .onDestruct(() => {
      if (fail.destruct) throw new Error("destruct failed");
    })
    .build();
  return { vm, fail };
}

const sharedSchedulerDispatchers: Array<[string, () => IDispatcher]> = [
  ["RxDispatcher.immediate()", () => RxDispatcher.immediate()],
  ["NullDispatcher.INSTANCE", () => NullDispatcher.INSTANCE],
];

describe.each(sharedSchedulerDispatchers)("background hook failure on %s", (_name, dispatcher) => {
  it("rolls a throwing onConstruct back to Destructed, and a retry constructs", () => {
    const { vm, fail } = failingVm(dispatcher());

    expect(() => vm.construct()).toThrow("construct failed");
    expect(vm.status).toBe(ConstructionStatus.Destructed);
    expect(vm.canConstruct()).toBe(true);

    fail.construct = false;
    vm.construct();
    expect(vm.status).toBe(ConstructionStatus.Constructed);
  });

  it("rolls a throwing onDestruct back to Constructed, and a retry destructs", () => {
    const { vm, fail } = failingVm(dispatcher());
    fail.construct = false;
    vm.construct();
    fail.destruct = true;

    expect(() => vm.destruct()).toThrow("destruct failed");
    expect(vm.status).toBe(ConstructionStatus.Constructed);
    expect(vm.canDestruct()).toBe(true);

    fail.destruct = false;
    vm.destruct();
    expect(vm.status).toBe(ConstructionStatus.Destructed);
  });
});

describe.each(sharedSchedulerDispatchers)("work queued by a rollback observer on %s", (_name, dispatcher) => {
  it("runs before construct() rethrows, so a VM the observer constructs is not left transient", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const { vm } = failingVm(shared, hub);
    const other = ComponentVM.builder().name("other").services(hub, shared).background(true).build();
    hub.messages.subscribe((message) => {
      if (
        message instanceof ConstructionStatusChangedMessage &&
        message.sender === vm &&
        message.status === ConstructionStatus.Destructed
      ) {
        other.construct();
      }
    });

    expect(() => vm.construct()).toThrow("construct failed");
    expect(vm.status).toBe(ConstructionStatus.Destructed);
    expect(other.status).toBe(ConstructionStatus.Constructed);
  });
});

describe("background hook failure with separate schedulers", () => {
  it("still publishes the rollback status on the foreground scheduler", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const hub = new MessageHub();
    const { vm } = failingVm(new RxDispatcher(foreground, background), hub);
    const published: ConstructionStatus[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage) published.push(message.status);
    });

    vm.construct();
    expect(() => background.flush()).toThrow("construct failed");
    // The rollback waits for the foreground: nothing is published yet.
    expect(vm.status).toBe(ConstructionStatus.Constructing);
    expect(published).toEqual([ConstructionStatus.Constructing]);

    foreground.flush();
    expect(vm.status).toBe(ConstructionStatus.Destructed);
    expect(published).toEqual([ConstructionStatus.Constructing, ConstructionStatus.Destructed]);
    expect(vm.canConstruct()).toBe(true);
  });
});
