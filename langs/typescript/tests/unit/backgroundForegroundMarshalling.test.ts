// VMX-025 regression: a background construct()/destruct() must marshal its
// terminal status emission (the Constructed/Destructed
// ConstructionStatusChangedMessage + propertyChanged) onto
// dispatcher.foreground so subscribers observe the terminal transition on the
// foreground (UI) thread, not the background (pool) thread.
//
// _onConstruct()/_onDestruct() still run on the background scheduler (THR-002);
// only the terminal emission hops to the foreground. The disposed re-check stays
// atomic — a dispose() landing before the marshalled emission runs still aborts
// it (see lifecycleRace.test.ts).

import { describe, expect, it } from "vitest";
import { TestScheduler } from "rxjs/testing";
import {
  ComponentVMOf,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

// Virtual-time scheduler whose queued work runs only on an explicit flush(),
// mirroring the sibling THR tests so the foreground hop is observable rather
// than masked by queueScheduler's synchronous trampoline.
function makeTestScheduler(): TestScheduler {
  return new TestScheduler((actual, expected) => {
    expect(actual).toEqual(expected);
  });
}

describe("VMX-025 background → foreground marshalling", () => {
  it("marshals the Constructed status emission onto the foreground scheduler", () => {
    const hub = new MessageHub();
    const foreground = makeTestScheduler();
    const background = makeTestScheduler();
    const disp = new RxDispatcher(foreground, background);

    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .background(true)
      .build();

    const constructedSeen: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (
        m instanceof ConstructionStatusChangedMessage &&
        m.status === ConstructionStatus.Constructed
      ) {
        constructedSeen.push(m.status);
      }
    });

    vm.construct();

    // Run _onConstruct on the background scheduler. The terminal Constructed
    // emission is now queued on the FOREGROUND scheduler — not emitted inline on
    // the background thread — so neither the status nor the hub message has
    // reached Constructed yet.
    background.flush();

    expect(
      vm.status,
      "the terminal Constructed emission is marshalled onto the foreground scheduler (VMX-025)",
    ).toBe(ConstructionStatus.Constructing);
    expect(
      constructedSeen,
      "the Constructed message must be delivered via the foreground scheduler, not inline on the background thread",
    ).toHaveLength(0);

    // Advance the foreground scheduler — the marshalled terminal emission runs.
    foreground.flush();

    expect(vm.status).toBe(ConstructionStatus.Constructed);
    expect(constructedSeen).toEqual([ConstructionStatus.Constructed]);
  });

  it("marshals the Destructed status emission onto the foreground scheduler", () => {
    const hub = new MessageHub();
    const foreground = makeTestScheduler();
    const background = makeTestScheduler();
    const disp = new RxDispatcher(foreground, background);

    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .background(true)
      .build();

    // Bring the VM to Constructed (drain both schedulers).
    vm.construct();
    background.flush();
    foreground.flush();
    expect(vm.status).toBe(ConstructionStatus.Constructed);

    const destructedSeen: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (
        m instanceof ConstructionStatusChangedMessage &&
        m.status === ConstructionStatus.Destructed
      ) {
        destructedSeen.push(m.status);
      }
    });

    vm.destruct();

    background.flush();

    expect(
      vm.status,
      "the terminal Destructed emission is marshalled onto the foreground scheduler (VMX-025)",
    ).toBe(ConstructionStatus.Destructing);
    expect(destructedSeen).toHaveLength(0);

    foreground.flush();

    expect(vm.status).toBe(ConstructionStatus.Destructed);
    expect(destructedSeen).toEqual([ConstructionStatus.Destructed]);
  });
});
