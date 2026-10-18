import { describe, it, expect } from "vitest";
import { observeOn, filter } from "rxjs/operators";
import { TestScheduler } from "rxjs/testing";
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

// A virtual-time scheduler whose queued work runs only on an explicit flush().
// This mirrors the C# Microsoft.Reactive.Testing.TestScheduler / Python
// reactivex TestScheduler used in the sibling THR tests, so the TypeScript
// tests prove deferral (zero deliveries before flush, exactly one after)
// rather than relying on queueScheduler's synchronous trampoline — which would
// pass even if the ObserveOn were removed entirely.
function makeTestScheduler(): TestScheduler {
  return new TestScheduler((actual, expected) => {
    expect(actual).toEqual(expected);
  });
}

// ---------------------------------------------------------------------------
// THR-001
// ---------------------------------------------------------------------------

describe("THR-001", () => {
  it("PropertyChanged observed on foreground scheduler buffers until it advances", () => {
    const hub = makeHub();
    const disp = RxDispatcher.immediate();
    const foreground = makeTestScheduler();

    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m1")
      .services(hub, disp)
      .build();

    const received: string[] = [];
    hub.messages.pipe(
      filter((m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage && m.propertyName === "model",
      ),
      observeOn(foreground),
    ).subscribe((m) => received.push(m.propertyName));

    vm.model = "m2";

    // Before advancing the foreground scheduler, delivery must be buffered.
    expect(received, "ObserveOn(foreground) must buffer delivery until the scheduler advances").toHaveLength(0);

    foreground.flush();

    expect(received).toHaveLength(1);
    expect(received[0]).toBe("model");
  });
});

// ---------------------------------------------------------------------------
// THR-002
// ---------------------------------------------------------------------------

describe("THR-002", () => {
  it("Background construct dispatches OnConstruct on the background scheduler", () => {
    const hub = makeHub();
    // Distinct virtual-time schedulers: the construction work (OnConstruct)
    // must be queued on dispatcher.background, and only the terminal
    // Constructed emission is marshalled back onto dispatcher.foreground.
    const foreground = makeTestScheduler();
    const background = makeTestScheduler();
    const disp = new RxDispatcher(foreground, background);

    let constructRuns = 0;
    const vm = ComponentVMOf.builder<string>()
      .name("v")
      .model("m")
      .services(hub, disp)
      .background(true)
      .onConstruct(() => { constructRuns++; })
      .build();

    vm.construct();

    // construct() returns immediately with only Constructing emitted; the
    // construction work has not run because neither scheduler has advanced.
    expect(vm.status, "Background(true) emits only Constructing synchronously").toBe(
      ConstructionStatus.Constructing,
    );
    expect(constructRuns, "OnConstruct must be deferred to the background scheduler").toBe(0);

    // Advancing ONLY the foreground must not run the construction work.
    foreground.flush();
    expect(constructRuns, "advancing the foreground alone must not run OnConstruct").toBe(0);
    expect(vm.status).toBe(ConstructionStatus.Constructing);

    // Advancing the background runs the construction work; the terminal
    // Constructed transition is still pending on the foreground.
    background.flush();
    expect(constructRuns, "advancing the background scheduler runs OnConstruct exactly once").toBe(1);
    expect(vm.status, "still Constructing after only background advances").toBe(
      ConstructionStatus.Constructing,
    );

    foreground.flush();
    expect(vm.status, "after the foreground advances the transition completes").toBe(
      ConstructionStatus.Constructed,
    );
    expect(constructRuns).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// THR-003
// ---------------------------------------------------------------------------

describe("THR-003", () => {
  it("CollectionChanged observed on foreground scheduler buffers until it advances", () => {
    const hub = makeHub();
    const disp = RxDispatcher.immediate();
    const foreground = makeTestScheduler();

    const child = ComponentVM.builder().name("c").services(hub, disp).build();
    const composite = CompositeVM.builder<ComponentVM>()
      .name("comp")
      .services(hub, disp)
      .children(() => [])
      .build();
    composite.construct();

    const received: string[] = [];
    composite.collectionChanged.pipe(
      observeOn(foreground),
    ).subscribe((e) => received.push(e.action));

    composite.add(child);

    // Before advancing the foreground scheduler, delivery must be buffered.
    expect(received, "ObserveOn(foreground) must buffer delivery until the scheduler advances").toHaveLength(0);

    foreground.flush();

    expect(received).toHaveLength(1);
    expect(received[0]).toBe("add");
  });
});

// ---------------------------------------------------------------------------
// THR-004
// ---------------------------------------------------------------------------

describe("THR-004", () => {
  it("Subscriber observes on chosen scheduler via ObserveOn, buffering until it advances", () => {
    const hub = makeHub();
    const scheduler = makeTestScheduler();
    const received: IMessage[] = [];

    hub.messages.pipe(
      observeOn(scheduler),
    ).subscribe((m) => received.push(m));

    const msg: IMessage = { senderName: "test", sender: {} };
    hub.send(msg);

    // Before advancing the scheduler, delivery must be buffered.
    expect(received, "ObserveOn(scheduler) must buffer delivery until the scheduler advances").toHaveLength(0);

    scheduler.flush();

    expect(received).toHaveLength(1);
    expect(received[0]).toBe(msg);
  });
});
