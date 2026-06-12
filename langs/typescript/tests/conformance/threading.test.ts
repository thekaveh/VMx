import { describe, it, expect } from "vitest";
import { observeOn, filter } from "rxjs/operators";
import { queueScheduler } from "rxjs";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  CompositeVM,
  ComponentVM,
  PropertyChangedMessage,
  ConstructionStatus,
} from "../../src/index.js";
import type { IMessage } from "../../src/index.js";

function makeHub() { return new MessageHub(); }

// ---------------------------------------------------------------------------
// THR-001
// ---------------------------------------------------------------------------

describe("THR-001", () => {
  it("PropertyChanged observed on foreground scheduler", () => {
    const hub = makeHub();
    const disp = RxDispatcher.immediate(); // queueScheduler = foreground

    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m1")
      .services(hub, disp)
      .build();

    const received: string[] = [];

    hub.messages.pipe(
      filter((m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage,
      ),
      observeOn(disp.foreground),
    ).subscribe((m) => received.push(m.propertyName));

    vm.model = "m2";

    // With queueScheduler (synchronous), the event is delivered synchronously.
    expect(received).toContain("model");
  });
});

// ---------------------------------------------------------------------------
// THR-002
// ---------------------------------------------------------------------------

describe("THR-002", () => {
  it("Background construct dispatches on background scheduler", () => {
    const scheduled: string[] = [];
    // Spy scheduler: records that work was scheduled.
    const spyScheduler = {
      schedule: (work: () => void) => {
        scheduled.push("background-scheduled");
        work(); // execute immediately for test purposes
        return { unsubscribe: () => undefined };
      },
      now: () => Date.now(),
    };

    const hub = makeHub();
    const disp = new RxDispatcher(queueScheduler, spyScheduler as never);

    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .background(true)
      .build();

    vm.construct();

    expect(scheduled).toContain("background-scheduled");
    expect(vm.status).toBe(ConstructionStatus.Constructed);
  });
});

// ---------------------------------------------------------------------------
// THR-003
// ---------------------------------------------------------------------------

describe("THR-003", () => {
  it("CollectionChanged observed on foreground scheduler", () => {
    const hub = makeHub();
    const disp = RxDispatcher.immediate();

    const child = ComponentVM.builder().name("c").services(hub, disp).build();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("comp")
      .services(hub, disp)
      .children(() => [])
      .build();
    composite.construct();

    const received: string[] = [];
    composite.collectionChanged.pipe(
      observeOn(disp.foreground),
    ).subscribe((e) => received.push(e.action));

    composite.add(child);

    // With queueScheduler, delivered synchronously.
    expect(received).toContain("add");
  });
});

// ---------------------------------------------------------------------------
// THR-004
// ---------------------------------------------------------------------------

describe("THR-004", () => {
  it("Subscriber observes on chosen scheduler via ObserveOn", () => {
    const hub = makeHub();
    const received: IMessage[] = [];

    hub.messages.pipe(
      observeOn(queueScheduler),
    ).subscribe((m) => received.push(m));

    const msg: IMessage = { senderName: "test", senderObject: {} };
    hub.send(msg);

    // queueScheduler is synchronous — delivery happens before send() returns.
    expect(received).toContain(msg);
  });
});
