// #1053: a background parent whose deferred child walk fails rolls back and
// releases the in-flight guard. The walk's continuation can run inside a flush
// of the foreground scheduler, and a throw there unsubscribes the queued
// rollback. #726 fixed the same drop for a throwing background hook.

import { afterEach, describe, expect, it, vi } from "vitest";
import { queueScheduler, type SchedulerLike } from "rxjs";
import { TestScheduler } from "rxjs/testing";
import {
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  NullDispatcher,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

/** A background parent that walks one background member in its hooks. */
class WalkingParentVM extends ComponentVMBase {
  readonly members: ComponentVMBase[] = [];
  failConstructAfter = false;
  failDestructAfter = false;
  failConstructHook = false;
  constructAfterError = "after failed";
  /** Runs at the end of each hook, after the walk has started. */
  afterWalk: (() => void) | null = null;

  constructor(hub: IMessageHub, dispatcher: IDispatcher, background = true, name = "parent") {
    super({ name, hub, dispatcher, background });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  register<T extends ComponentVMBase>(member: T): T {
    this.members.push(member);
    return this.ownMember(member);
  }

  protected override _onConstruct(): void {
    if (this.failConstructHook) throw new Error("construct hook failed");
    super._onConstruct();
    this._transitionChildren(this.members, true, () => {
      if (this.failConstructAfter) throw new Error(this.constructAfterError);
    });
    this.afterWalk?.();
  }

  protected override _onDestruct(): void {
    this._transitionChildren([...this.members].reverse(), false, () => {
      if (this.failDestructAfter) throw new Error("destruct after failed");
      super._onDestruct();
    });
    this.afterWalk?.();
  }
}

function parentWithBackgroundMember(
  dispatcher: IDispatcher,
  hub: IMessageHub = new MessageHub(),
  background = true,
) {
  const parent = new WalkingParentVM(hub, dispatcher, background);
  parent.register(
    ComponentVM.builder().name("member").services(hub, dispatcher).background(true).build(),
  );
  return parent;
}

/** A background VM with no members. */
function backgroundVM(dispatcher: IDispatcher, hub: IMessageHub, name = "member") {
  return ComponentVM.builder().name(name).services(hub, dispatcher).background(true).build();
}

/** Run `run` once `vm` publishes `status` on `hub`. */
function onStatus(hub: IMessageHub, vm: ComponentVMBase, status: ConstructionStatus, run: () => void) {
  hub.messages.subscribe((message) => {
    if (
      message instanceof ConstructionStatusChangedMessage &&
      message.sender === vm &&
      message.status === status
    ) {
      run();
    }
  });
}

/** Fail with a clear message instead of hanging if `scheduler` keeps re-queueing work. */
function guardAgainstSpin(scheduler: SchedulerLike, limit = 10_000) {
  const schedule = scheduler.schedule.bind(scheduler);
  let calls = 0;
  vi.spyOn(scheduler, "schedule").mockImplementation((...args: Parameters<typeof schedule>) => {
    if (++calls > limit) throw new Error(`scheduled more than ${String(limit)} actions`);
    return schedule(...args);
  });
}

/** Flush both test schedulers a few rounds and return the first error thrown. */
function flushRounds(foreground: TestScheduler, background: TestScheduler, rounds = 4): unknown {
  let thrown: unknown;
  for (let round = 0; round < rounds; round++) {
    try {
      background.flush();
    } catch (error) {
      thrown ??= error;
    }
    try {
      foreground.flush();
    } catch (error) {
      thrown ??= error;
    }
  }
  return thrown;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** An outer walking parent whose only member is itself a walking parent. */
function nestedParents(dispatcher: IDispatcher, hub: IMessageHub = new MessageHub()) {
  const outer = new WalkingParentVM(hub, dispatcher);
  const inner = outer.register(parentWithBackgroundMember(dispatcher, hub));
  return { outer, inner };
}

/** A background member whose own construct hook can throw. */
function failingMember(dispatcher: IDispatcher, hub: IMessageHub, fail: { construct: boolean }) {
  return ComponentVM.builder()
    .name("member")
    .services(hub, dispatcher)
    .background(true)
    .onConstruct(() => {
      if (fail.construct) throw new Error("member failed");
    })
    .build();
}

const sharedSchedulerDispatchers: Array<[string, () => IDispatcher]> = [
  ["RxDispatcher.immediate()", () => RxDispatcher.immediate()],
  ["NullDispatcher.INSTANCE", () => NullDispatcher.INSTANCE],
];

describe.each(sharedSchedulerDispatchers)("deferred child walk failure on %s", (_name, dispatcher) => {
  it("rolls a failing construct walk back to Destructed, and a retry constructs", () => {
    const parent = parentWithBackgroundMember(dispatcher());
    parent.failConstructAfter = true;

    expect(() => parent.construct()).toThrow("after failed");
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);

    parent.failConstructAfter = false;
    parent.construct();
    expect(parent.status).toBe(ConstructionStatus.Constructed);
  });

  it("rolls a failing destruct walk back to Constructed, and a retry destructs", () => {
    const parent = parentWithBackgroundMember(dispatcher());
    parent.construct();
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    parent.failDestructAfter = true;

    expect(() => parent.destruct()).toThrow("destruct after failed");
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    expect(parent.canDestruct()).toBe(true);

    parent.failDestructAfter = false;
    parent.destruct();
    expect(parent.status).toBe(ConstructionStatus.Destructed);
  });
});

describe.each(sharedSchedulerDispatchers)("nested deferred walk failure on %s", (_name, dispatcher) => {
  it("rolls both walking parents back when the inner walk fails", () => {
    const { outer, inner } = nestedParents(dispatcher());
    inner.failConstructAfter = true;

    expect(() => outer.construct()).toThrow("after failed");
    expect(inner.status).toBe(ConstructionStatus.Destructed);
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(outer.canConstruct()).toBe(true);

    inner.failConstructAfter = false;
    outer.construct();
    expect(outer.status).toBe(ConstructionStatus.Constructed);
    expect(inner.status).toBe(ConstructionStatus.Constructed);
  });

  it("rolls three levels of walking parents back when the innermost walk fails", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const outer = new WalkingParentVM(hub, shared);
    const { outer: middle, inner } = nestedParents(shared, hub);
    outer.register(middle);
    inner.failConstructAfter = true;

    expect(() => outer.construct()).toThrow("after failed");
    expect([inner.status, middle.status, outer.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(outer.canConstruct()).toBe(true);
  });

  it("rolls the walking parent back when a background member's hook throws", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const fail = { construct: true };
    const parent = new WalkingParentVM(hub, shared);
    const member = parent.register(failingMember(shared, hub, fail));

    expect(() => parent.construct()).toThrow("member failed");
    expect(member.status).toBe(ConstructionStatus.Destructed);
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);

    fail.construct = false;
    parent.construct();
    expect(parent.status).toBe(ConstructionStatus.Constructed);
  });
});

describe.each(sharedSchedulerDispatchers)("a failing foreground walk under a background parent on %s", (_name, dispatcher) => {
  /** A background parent over a foreground walking parent over a background member. */
  function threeTier(shared: IDispatcher) {
    const hub = new MessageHub();
    const outer = new WalkingParentVM(hub, shared);
    const middle = outer.register(new WalkingParentVM(hub, shared, false));
    middle.register(
      ComponentVM.builder().name("member").services(hub, shared).background(true).build(),
    );
    return { outer, middle };
  }

  it("rolls the background parent back when the foreground parent's construct walk fails", () => {
    const { outer, middle } = threeTier(dispatcher());
    middle.failConstructAfter = true;

    expect(() => outer.construct()).toThrow("after failed");
    expect(middle.status).toBe(ConstructionStatus.Destructed);
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(outer.canConstruct()).toBe(true);
  });

  it("rolls the background parent back when the foreground parent's destruct walk fails", () => {
    const { outer, middle } = threeTier(dispatcher());
    outer.construct();
    middle.failDestructAfter = true;

    expect(() => outer.destruct()).toThrow("destruct after failed");
    expect(middle.status).toBe(ConstructionStatus.Constructed);
    expect(outer.status).toBe(ConstructionStatus.Constructed);
    expect(outer.canDestruct()).toBe(true);
  });

  it("rolls the background parent back when a composite member's selector throws", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const parent = new WalkingParentVM(hub, shared);
    const leaf = ComponentVM.builder().name("leaf").services(hub, shared).background(true).build();
    const composite = parent.register(
      CompositeVM.builder<ComponentVM>()
        .name("composite")
        .services(hub, shared)
        .children(() => [leaf])
        .current(() => {
          throw new Error("selector failed");
        })
        .build(),
    );

    expect(() => parent.construct()).toThrow("selector failed");
    expect(composite.status).toBe(ConstructionStatus.Destructed);
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);
  });
});

describe("three levels of walking parents with no synchronous drain", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function threeLevels(dispatcher: IDispatcher) {
    const hub = new MessageHub();
    const outer = new WalkingParentVM(hub, dispatcher);
    const { outer: middle, inner } = nestedParents(dispatcher, hub);
    outer.register(middle);
    inner.failConstructAfter = true;
    return { outer, middle, inner };
  }

  it("rolls every level back with separate schedulers", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const { outer, middle, inner } = threeLevels(new RxDispatcher(foreground, background));

    outer.construct();
    let thrown: unknown;
    for (let round = 0; round < 5; round++) {
      background.flush();
      try {
        foreground.flush();
      } catch (error) {
        thrown = error;
      }
    }

    expect((thrown as Error).message).toBe("after failed");
    expect([inner.status, middle.status, outer.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(outer.canConstruct()).toBe(true);
  });

  it("rolls every level back on RxDispatcher.default()", () => {
    vi.useFakeTimers();
    const { outer, middle, inner } = threeLevels(RxDispatcher.default());

    outer.construct();
    expect(() => vi.runAllTimers()).toThrow("after failed");
    vi.runAllTimers();

    expect([inner.status, middle.status, outer.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(outer.canConstruct()).toBe(true);
  });
});

describe("a background parent that joins a reconstructing child", () => {
  /** A background parent over a foreground walking parent over a background member. */
  function joinTree(dispatcher: IDispatcher) {
    const hub = new MessageHub();
    const outer = new WalkingParentVM(hub, dispatcher, true, "outer");
    const middle = outer.register(new WalkingParentVM(hub, dispatcher, false, "middle"));
    middle.register(backgroundVM(dispatcher, hub));
    return { outer, middle };
  }

  it("rolls back when the child's destruct walk fails, with separate schedulers", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const { outer, middle } = joinTree(new RxDispatcher(foreground, background));
    outer.construct();
    flushRounds(foreground, background);
    expect(outer.status).toBe(ConstructionStatus.Constructed);
    middle.failDestructAfter = true;

    middle.reconstruct();
    outer.destruct();
    const thrown = flushRounds(foreground, background);

    expect((thrown as Error).message).toBe("destruct after failed");
    expect(middle.status).toBe(ConstructionStatus.Constructed);
    expect(outer.status).toBe(ConstructionStatus.Constructed);
    expect(outer.canDestruct()).toBe(true);
  });

  it.each(sharedSchedulerDispatchers)(
    "rolls back when the child's destruct walk fails inside a flush on %s",
    (_name, dispatcher) => {
      const { outer, middle } = joinTree(dispatcher());
      outer.construct();
      middle.failDestructAfter = true;

      expect(() =>
        queueScheduler.schedule(() => {
          middle.reconstruct();
          outer.destruct();
        }),
      ).toThrow("destruct after failed");
      expect(middle.status).toBe(ConstructionStatus.Constructed);
      expect(outer.status).toBe(ConstructionStatus.Constructed);
      expect(outer.canDestruct()).toBe(true);
    },
  );

  it("finishes the parent's destruct when the child's construct hook fails, with separate schedulers", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const { outer, middle } = joinTree(new RxDispatcher(foreground, background));
    outer.construct();
    flushRounds(foreground, background);
    middle.failConstructHook = true;

    middle.reconstruct();
    outer.destruct();
    const thrown = flushRounds(foreground, background);

    expect((thrown as Error).message).toBe("construct hook failed");
    expect(middle.status).toBe(ConstructionStatus.Destructed);
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(outer.canConstruct()).toBe(true);
  });

  it("finishes the parent's destruct when the child's construct hook fails, on RxDispatcher.default()", () => {
    vi.useFakeTimers();
    const { outer, middle } = joinTree(RxDispatcher.default());
    outer.construct();
    vi.runAllTimers();
    middle.failConstructHook = true;

    outer.destruct();
    middle.reconstruct();
    expect(() => vi.runAllTimers()).toThrow("construct hook failed");
    vi.runAllTimers();

    expect(middle.status).toBe(ConstructionStatus.Destructed);
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(outer.canConstruct()).toBe(true);
  });
});

describe.each(sharedSchedulerDispatchers)("rollback failures in one flush on %s", (_name, dispatcher) => {
  it("rolls every member back when one walking member fails", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const outer = new WalkingParentVM(hub, shared, true, "outer");
    const first = outer.register(parentWithBackgroundMember(shared, hub));
    const second = outer.register(parentWithBackgroundMember(shared, hub));
    first.failConstructAfter = true;

    expect(() => outer.construct()).toThrow("after failed");
    expect([first.status, second.status, outer.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(outer.canConstruct()).toBe(true);
  });

  it("throws the first of two independent failures and rolls both back", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const first = parentWithBackgroundMember(shared, hub);
    const second = parentWithBackgroundMember(shared, hub);
    first.failConstructAfter = true;
    first.constructAfterError = "first failed";
    second.failConstructAfter = true;
    second.constructAfterError = "second failed";
    const starter = ComponentVM.builder()
      .name("starter")
      .services(hub, shared)
      .background(true)
      .onConstruct(() => {
        first.construct();
        second.construct();
      })
      .build();

    expect(() => starter.construct()).toThrow("first failed");
    expect([first.status, second.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(first.canConstruct() && second.canConstruct()).toBe(true);
  });

  it("rolls back two independent failures inside a caller's flush", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const first = parentWithBackgroundMember(shared, hub);
    const second = parentWithBackgroundMember(shared, hub);
    first.failConstructAfter = true;
    second.failConstructAfter = true;

    // No drain records these failures, so each one goes to the throw that waits
    // for the counted actions. The first of those throws to run leaves the
    // flush, and the flush drops the other one with its error.
    expect(() =>
      queueScheduler.schedule(() => {
        first.construct();
        second.construct();
      }),
    ).toThrow("after failed");
    expect([first.status, second.status]).toEqual([
      ConstructionStatus.Destructed,
      ConstructionStatus.Destructed,
    ]);
    expect(first.canConstruct() && second.canConstruct()).toBe(true);
  });

  /** A background parent over a failing foreground walking parent. */
  function failingTiers(shared: IDispatcher, hub: IMessageHub) {
    const outer = new WalkingParentVM(hub, shared, true, "outer");
    const middle = outer.register(new WalkingParentVM(hub, shared, false, "middle"));
    middle.register(backgroundVM(shared, hub));
    middle.failConstructAfter = true;
    return outer;
  }

  /** Failing tiers whose rollback constructs another background VM. */
  function observedRollback(shared: IDispatcher) {
    const hub = new MessageHub();
    const outer = failingTiers(shared, hub);
    const other = backgroundVM(shared, hub, "other");
    onStatus(hub, outer, ConstructionStatus.Destructed, () => {
      other.construct();
    });
    return { outer, other };
  }

  it("runs work that a rollback observer queues before construct() rethrows", () => {
    const { outer, other } = observedRollback(dispatcher());

    expect(() => outer.construct()).toThrow("after failed");
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(other.status).toBe(ConstructionStatus.Constructed);
  });

  it("runs caller work that a rollback observer schedules before construct() rethrows", () => {
    const shared = dispatcher();
    const hub = new MessageHub();
    const outer = failingTiers(shared, hub);
    let ran = false;
    onStatus(hub, outer, ConstructionStatus.Destructed, () => {
      shared.foreground.schedule(() => {
        ran = true;
      });
    });

    expect(() => outer.construct()).toThrow("after failed");
    expect(ran).toBe(true);
  });

  it("runs work that a rollback observer queues inside a caller's flush", () => {
    const { outer, other } = observedRollback(dispatcher());

    expect(() =>
      queueScheduler.schedule(() => {
        outer.construct();
      }),
    ).toThrow("after failed");
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(other.status).toBe(ConstructionStatus.Constructed);
  });
});

describe("a completion that never runs", () => {
  it("does not stall a later failure after a throw dropped a completion", () => {
    vi.useFakeTimers();
    const hub = new MessageHub();
    const dropped = backgroundVM(RxDispatcher.immediate(), hub, "dropped");
    expect(() =>
      queueScheduler.schedule(() => {
        dropped.construct();
        queueScheduler.schedule(() => {
          throw new Error("caller failed");
        });
      }),
    ).toThrow("caller failed");

    const parent = parentWithBackgroundMember(RxDispatcher.default(), hub);
    parent.failConstructAfter = true;
    guardAgainstSpin(queueScheduler);
    parent.construct();

    expect(() => vi.runAllTimers()).toThrow("after failed");
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);
  });

  it("does not stall a later failure after an override skipped a completion", () => {
    class SkippingVM extends WalkingParentVM {
      skipForeground = false;

      protected override _scheduleForeground(work: () => void): void {
        if (!this.skipForeground) super._scheduleForeground(work);
      }
    }
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const dispatcher = new RxDispatcher(foreground, background);
    const hub = new MessageHub();
    const skipping = new SkippingVM(hub, dispatcher);
    skipping.skipForeground = true;
    skipping.construct();
    flushRounds(foreground, background);

    const parent = parentWithBackgroundMember(dispatcher, hub);
    parent.failConstructAfter = true;
    guardAgainstSpin(foreground);
    parent.construct();

    expect((flushRounds(foreground, background) as Error).message).toBe("after failed");
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);
  });
});

describe("a hook that settles its own walk before it returns", () => {
  /** A foreground parent whose hooks flush both schedulers after the walk starts. */
  function selfSettlingParent() {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const parent = parentWithBackgroundMember(
      new RxDispatcher(foreground, background),
      new MessageHub(),
      false,
    );
    parent.afterWalk = () => {
      background.flush();
      foreground.flush();
    };
    return { parent, foreground, background };
  }

  it("makes construct() throw the walk failure to its caller", () => {
    const { parent, foreground, background } = selfSettlingParent();
    parent.failConstructAfter = true;

    expect(() => parent.construct()).toThrow("after failed");
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(parent.canConstruct()).toBe(true);
    expect(flushRounds(foreground, background)).toBeUndefined();
  });

  it("makes reconstruct() throw the destruct walk failure to its caller", () => {
    const { parent, foreground, background } = selfSettlingParent();
    parent.construct();
    parent.failDestructAfter = true;

    expect(() => parent.reconstruct()).toThrow("destruct after failed");
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    expect(parent.canReconstruct()).toBe(true);
    expect(flushRounds(foreground, background)).toBeUndefined();
  });
});

describe("a reconstructing parent with separate schedulers", () => {
  it("returns the reconstructing parent to Constructed with separate schedulers", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const shared = new RxDispatcher(foreground, background);
    const hub = new MessageHub();
    const parent = new WalkingParentVM(hub, shared, false);
    const fail = { destruct: false };
    parent.register(
      ComponentVM.builder()
        .name("member")
        .services(hub, shared)
        .background(true)
        .onDestruct(() => {
          if (fail.destruct) throw new Error("member destruct failed");
        })
        .build(),
    );
    parent.construct();
    background.flush();
    foreground.flush();
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    fail.destruct = true;

    parent.reconstruct();
    expect(() => background.flush()).toThrow("member destruct failed");
    foreground.flush();

    expect(parent.status).toBe(ConstructionStatus.Constructed);
    expect(parent.canReconstruct()).toBe(true);
    fail.destruct = false;
    parent.reconstruct();
    background.flush();
    foreground.flush();
    background.flush();
    foreground.flush();
    expect(parent.status).toBe(ConstructionStatus.Constructed);
  });
});

describe("a reconstruct whose destruct walk fails", () => {
  it.each(sharedSchedulerDispatchers)("returns to Constructed on %s", (_name, dispatcher) => {
    const parent = parentWithBackgroundMember(dispatcher());
    parent.construct();
    parent.failDestructAfter = true;

    expect(() => parent.reconstruct()).toThrow("destruct after failed");
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    expect(parent.canReconstruct()).toBe(true);
  });

  it("throws from the foreground after the rollback with separate schedulers", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const parent = parentWithBackgroundMember(new RxDispatcher(foreground, background));
    parent.construct();
    for (let round = 0; round < 2; round++) {
      background.flush();
      foreground.flush();
    }
    expect(parent.status).toBe(ConstructionStatus.Constructed);
    parent.failDestructAfter = true;

    parent.reconstruct();
    background.flush();
    expect(() => foreground.flush()).toThrow("destruct after failed");
    foreground.flush();

    expect(parent.status).toBe(ConstructionStatus.Constructed);
    expect(parent.canReconstruct()).toBe(true);
  });
});

describe("deferred child walk failure with separate schedulers", () => {
  it("rolls both walking parents back when the inner walk fails", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const { outer, inner } = nestedParents(new RxDispatcher(foreground, background));
    inner.failConstructAfter = true;

    outer.construct();
    background.flush();
    expect(() => foreground.flush()).toThrow("after failed");
    background.flush();
    foreground.flush();

    expect(inner.status).toBe(ConstructionStatus.Destructed);
    expect(outer.status).toBe(ConstructionStatus.Destructed);
    expect(outer.canConstruct()).toBe(true);
  });

  it("still publishes the rollback status on the foreground scheduler", () => {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const hub = new MessageHub();
    const parent = parentWithBackgroundMember(new RxDispatcher(foreground, background), hub);
    const published: ConstructionStatus[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.sender === parent) {
        published.push(message.status);
      }
    });
    parent.failConstructAfter = true;

    parent.construct();
    background.flush();
    // The member settles on the foreground, and only then does the walk fail.
    expect(parent.status).toBe(ConstructionStatus.Constructing);

    expect(() => foreground.flush()).toThrow("after failed");
    expect(parent.status).toBe(ConstructionStatus.Destructed);
    expect(published).toEqual([ConstructionStatus.Constructing, ConstructionStatus.Destructed]);
    expect(parent.canConstruct()).toBe(true);
  });
});
