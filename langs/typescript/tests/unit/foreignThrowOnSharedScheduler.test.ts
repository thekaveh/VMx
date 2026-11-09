// #1052: a throw from work that VMx did not queue, inside a flush of a shared
// queueScheduler, unsubscribes every action queued behind it. VMx lifecycle
// actions in that queue (background hook work, terminal completions and
// rollbacks) still run, so the VM settles and its in-flight guard is released.
//
// Error delivery, decided under the owner's 2026-11-07 delegation as the #1053
// rule extended to non-VMx work: each flush surfaces one error. The outermost
// background construct() or destruct() throws the first failure of its flush,
// where a throw out of the flush counts when it throws. Without such a call,
// the first throw to leave the flush leaves it. ADR-0200 §2.3: every other
// failure of the flush goes once to rxjs config.onUnhandledError after the
// flush returns.

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  queueScheduler,
  Subscription,
  type SchedulerAction,
  type SchedulerLike,
} from "rxjs";
import { TestScheduler } from "rxjs/testing";
import {
  ComponentVM,
  ComponentVMBase,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  NullDispatcher,
  RxDispatcher,
  markSchedulerCancelled,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";
import { ManualDispatcher } from "../../src/testing/index.js";
import { captureRxUnhandledErrors } from "../setup.js";

/** Let rxjs deliver the unhandled-error reports it queued on a timer. */
async function afterReports(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function messagesOf(errors: unknown[]): string[] {
  return errors.map((error) => (error as Error).message);
}

interface Hooks {
  construct?: () => void;
  destruct?: () => void;
}

/** A background VM whose hooks run `hooks.construct` and `hooks.destruct` when set. */
function backgroundVM(dispatcher: IDispatcher, hub: IMessageHub, name: string, hooks: Hooks = {}) {
  return ComponentVM.builder()
    .name(name)
    .services(hub, dispatcher)
    .background(true)
    .onConstruct(() => hooks.construct?.())
    .onDestruct(() => hooks.destruct?.())
    .build();
}

/** Queue a non-VMx action that throws `message` on `scheduler`. */
function queueThrow(scheduler: SchedulerLike, message: string): void {
  scheduler.schedule(() => {
    throw new Error(message);
  });
}

/** Run `run` inside one action of the shared queueScheduler and return what it throws. */
function inCallerFlush(run: () => void): unknown {
  try {
    queueScheduler.schedule(run);
  } catch (error) {
    return error;
  }
  return undefined;
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

function expectSettled(vm: ComponentVMBase, status: ConstructionStatus) {
  expect(vm.status).toBe(status);
  expect(vm.canConstruct()).toBe(true);
  expect(vm.canDestruct()).toBe(true);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("rxjs queueScheduler flush error (the mechanism #1052 relies on)", () => {
  it("runs a finalizer only for an action that the flush error drops", () => {
    const finalized: string[] = [];
    expect(() =>
      queueScheduler.schedule(() => {
        queueScheduler.schedule(() => undefined).add(() => finalized.push("ran"));
        queueScheduler.schedule(() => {
          throw new Error("boom");
        });
        queueScheduler.schedule(() => undefined).add(() => finalized.push("dropped"));
      }),
    ).toThrow("boom");
    expect(finalized).toEqual(["dropped"]);
  });
});

const sharedSchedulerDispatchers: Array<[string, () => IDispatcher]> = [
  ["RxDispatcher.immediate()", () => RxDispatcher.immediate()],
  ["NullDispatcher.INSTANCE", () => NullDispatcher.INSTANCE],
];

describe.each(sharedSchedulerDispatchers)("non-VMx throw on %s", (_name, dispatcher) => {
  describe("case 1: a failing hook queues a throwing action", () => {
    it("construct() rolls back to Destructed, throws the hook failure and reports the other", async () => {
      const reports = captureRxUnhandledErrors();
      const d = dispatcher();
      const vm = backgroundVM(d, new MessageHub(), "vm", {
        construct: () => {
          queueThrow(d.foreground, "queued work failed");
          throw new Error("hook failed");
        },
      });

      expect(() => vm.construct()).toThrow("hook failed");
      expectSettled(vm, ConstructionStatus.Destructed);
      expect(reports).toEqual([]);
      await afterReports();
      expect(messagesOf(reports)).toEqual(["queued work failed"]);
    });

    it("destruct() rolls back to Constructed, throws the hook failure and reports the other", async () => {
      const reports = captureRxUnhandledErrors();
      const d = dispatcher();
      const hooks: Hooks = {};
      const vm = backgroundVM(d, new MessageHub(), "vm", hooks);
      vm.construct();
      hooks.destruct = () => {
        queueThrow(d.foreground, "queued work failed");
        throw new Error("hook failed");
      };

      expect(() => vm.destruct()).toThrow("hook failed");
      expectSettled(vm, ConstructionStatus.Constructed);
      expect(reports).toEqual([]);
      await afterReports();
      expect(messagesOf(reports)).toEqual(["queued work failed"]);
    });
  });

  describe("case 1b: a passing hook queues a throwing action", () => {
    it("construct() reaches Constructed and throws the queued failure", () => {
      const d = dispatcher();
      const vm = backgroundVM(d, new MessageHub(), "vm", {
        construct: () => queueThrow(d.foreground, "queued work failed"),
      });

      expect(() => vm.construct()).toThrow("queued work failed");
      expectSettled(vm, ConstructionStatus.Constructed);
    });

    it("destruct() reaches Destructed and throws the queued failure", () => {
      const d = dispatcher();
      const hooks: Hooks = {};
      const vm = backgroundVM(d, new MessageHub(), "vm", hooks);
      vm.construct();
      hooks.destruct = () => queueThrow(d.foreground, "queued work failed");

      expect(() => vm.destruct()).toThrow("queued work failed");
      expectSettled(vm, ConstructionStatus.Destructed);
    });
  });

  describe("case 2: a failing VM and a passing VM in one caller action", () => {
    function pair() {
      const d = dispatcher();
      const hub = new MessageHub();
      const fail = { construct: false, destruct: false };
      const bad = backgroundVM(d, hub, "bad", {
        construct: () => {
          if (fail.construct) throw new Error("bad failed");
        },
        destruct: () => {
          if (fail.destruct) throw new Error("bad failed");
        },
      });
      const good = backgroundVM(d, hub, "good");
      return { bad, good, fail };
    }

    it.each([
      ["bad first", true],
      ["good first", false],
    ])("construct() settles both VMs (%s)", (_order, badFirst) => {
      const { bad, good, fail } = pair();
      fail.construct = true;

      const thrown = inCallerFlush(() => {
        if (badFirst) bad.construct();
        good.construct();
        if (!badFirst) bad.construct();
      });

      expect((thrown as Error).message).toBe("bad failed");
      expectSettled(bad, ConstructionStatus.Destructed);
      expectSettled(good, ConstructionStatus.Constructed);
    });

    it.each([
      ["bad first", true],
      ["good first", false],
    ])("destruct() settles both VMs (%s)", (_order, badFirst) => {
      const { bad, good, fail } = pair();
      bad.construct();
      good.construct();
      fail.destruct = true;

      const thrown = inCallerFlush(() => {
        if (badFirst) bad.destruct();
        good.destruct();
        if (!badFirst) bad.destruct();
      });

      expect((thrown as Error).message).toBe("bad failed");
      expectSettled(bad, ConstructionStatus.Constructed);
      expectSettled(good, ConstructionStatus.Destructed);
    });
  });

  describe("case 3: a caller action queues a throw next to a passing VM", () => {
    it.each([
      ["after", true],
      ["before", false],
    ])("construct() reaches Constructed with the throw queued %s it", (_order, throwAfter) => {
      const good = backgroundVM(dispatcher(), new MessageHub(), "good");

      const thrown = inCallerFlush(() => {
        if (!throwAfter) queueThrow(queueScheduler, "caller failed");
        good.construct();
        if (throwAfter) queueThrow(queueScheduler, "caller failed");
      });

      expect((thrown as Error).message).toBe("caller failed");
      expectSettled(good, ConstructionStatus.Constructed);
      good.destruct();
      expect(good.status).toBe(ConstructionStatus.Destructed);
    });

    it.each([
      ["after", true],
      ["before", false],
    ])("destruct() reaches Destructed with the throw queued %s it", (_order, throwAfter) => {
      const good = backgroundVM(dispatcher(), new MessageHub(), "good");
      good.construct();

      const thrown = inCallerFlush(() => {
        if (!throwAfter) queueThrow(queueScheduler, "caller failed");
        good.destruct();
        if (throwAfter) queueThrow(queueScheduler, "caller failed");
      });

      expect((thrown as Error).message).toBe("caller failed");
      expectSettled(good, ConstructionStatus.Destructed);
      good.construct();
      expect(good.status).toBe(ConstructionStatus.Constructed);
    });

    it("still drops the non-VMx actions queued behind the throw", () => {
      const good = backgroundVM(dispatcher(), new MessageHub(), "good");
      let foreignRan = false;

      const thrown = inCallerFlush(() => {
        queueThrow(queueScheduler, "caller failed");
        good.construct();
        queueScheduler.schedule(() => {
          foreignRan = true;
        });
      });

      expect((thrown as Error).message).toBe("caller failed");
      expect(good.status).toBe(ConstructionStatus.Constructed);
      expect(foreignRan).toBe(false);
    });
  });

  describe("a recovered action that fails", () => {
    it("settles the VM, keeps the caller's error and reports the recovered failure", async () => {
      const reports = captureRxUnhandledErrors();
      const d = dispatcher();
      guardAgainstSpin(d.foreground);
      const bad = backgroundVM(d, new MessageHub(), "bad", {
        construct: () => {
          throw new Error("bad failed");
        },
      });

      // The throw drops bad's background action. Its recovery runs the hook,
      // which fails after the caller's error already leaves the flush.
      const thrown = inCallerFlush(() => {
        queueThrow(queueScheduler, "caller failed");
        bad.construct();
      });

      expect(thrown).toBeInstanceOf(Error);
      expect((thrown as Error).message).toBe("caller failed");
      expectSettled(bad, ConstructionStatus.Destructed);
      // Nothing is reported before the flush's caller returns.
      expect(reports).toEqual([]);
      await afterReports();
      expect(messagesOf(reports)).toEqual(["bad failed"]);
    });

    it("keeps the non-VMx error that left first under an active construct()", async () => {
      const reports = captureRxUnhandledErrors();
      const d = dispatcher();
      const hub = new MessageHub();
      const bad = backgroundVM(d, hub, "bad", {
        construct: () => {
          throw new Error("bad failed");
        },
      });
      const outer = backgroundVM(d, hub, "outer", {
        construct: () => {
          queueThrow(d.foreground, "queued work failed");
          bad.construct();
        },
      });

      expect(() => outer.construct()).toThrow("queued work failed");
      expectSettled(outer, ConstructionStatus.Constructed);
      expectSettled(bad, ConstructionStatus.Destructed);
      expect(reports).toEqual([]);
      await afterReports();
      expect(messagesOf(reports)).toEqual(["bad failed"]);
    });
  });

  it("lets a status observer that schedules during recovery start a nested flush", () => {
    // rxjs behavior, pinned: the flush is no longer active while it unsubscribes
    // the dropped actions. An observer that schedules then starts a new flush,
    // and that flush runs the dropped actions that are still queued.
    const hub = new MessageHub();
    const good = backgroundVM(dispatcher(), hub, "good");
    let observerRan = false;
    let foreignRan = false;
    hub.messages.subscribe((message) => {
      if (
        message instanceof ConstructionStatusChangedMessage &&
        message.sender === good &&
        message.status === ConstructionStatus.Constructed
      ) {
        queueScheduler.schedule(() => {
          observerRan = true;
        });
      }
    });

    const thrown = inCallerFlush(() => {
      queueThrow(queueScheduler, "caller failed");
      good.construct();
      queueScheduler.schedule(() => {
        foreignRan = true;
      });
    });

    expect((thrown as Error).message).toBe("caller failed");
    expect(good.status).toBe(ConstructionStatus.Constructed);
    expect(observerRan).toBe(true);
    expect(foreignRan).toBe(true);
  });
});

describe("non-VMx throw with separate schedulers", () => {
  function setup() {
    const foreground = new TestScheduler(() => undefined);
    const background = new TestScheduler(() => undefined);
    const hub = new MessageHub();
    const fail = { construct: false };
    const vm = backgroundVM(new RxDispatcher(foreground, background), hub, "vm", {
      construct: () => {
        if (fail.construct) throw new Error("hook failed");
      },
    });
    let onForeground = false;
    const published: Array<[ConstructionStatus, boolean]> = [];
    hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.sender === vm) {
        published.push([message.status, onForeground]);
      }
    });
    const flushForeground = (): unknown => {
      onForeground = true;
      try {
        foreground.flush();
      } catch (error) {
        return error;
      } finally {
        onForeground = false;
      }
      return undefined;
    };
    return { foreground, background, vm, fail, published, flushForeground };
  }

  it("publishes a recovered terminal status on the foreground", () => {
    const { foreground, background, vm, published, flushForeground } = setup();
    queueThrow(foreground, "foreground failed");
    vm.construct();
    background.flush();

    expect((flushForeground() as Error).message).toBe("foreground failed");
    expectSettled(vm, ConstructionStatus.Constructed);
    expect(published.at(-1)).toEqual([ConstructionStatus.Constructed, true]);
  });

  it("publishes a recovered rollback status on the foreground", () => {
    const { foreground, background, vm, fail, published, flushForeground } = setup();
    fail.construct = true;
    queueThrow(foreground, "foreground failed");
    vm.construct();
    // With separate schedulers the hook failure still throws on the background (#842).
    expect(() => background.flush()).toThrow("hook failed");

    expect((flushForeground() as Error).message).toBe("foreground failed");
    expectSettled(vm, ConstructionStatus.Destructed);
    expect(published.at(-1)).toEqual([ConstructionStatus.Destructed, true]);
  });
});

describe("a scheduler that cancels its queued work", () => {
  // ManualDispatcher.dispose() cancels pending work by unsubscribing it. That is
  // not a flush error, so VMx must not run the cancelled lifecycle actions.
  function setup() {
    const dispatcher = new ManualDispatcher();
    const hub = new MessageHub();
    let hookRuns = 0;
    const vm = backgroundVM(dispatcher, hub, "vm", { construct: () => hookRuns++ });
    const published: ConstructionStatus[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.sender === vm) {
        published.push(message.status);
      }
    });
    return { dispatcher, vm, published, hookRuns: () => hookRuns };
  }

  it("does not run a cancelled background hook", () => {
    const { dispatcher, vm, published, hookRuns } = setup();
    vm.construct();
    const before = [...published];

    dispatcher.dispose();

    expect(hookRuns()).toBe(0);
    expect(published).toEqual(before);
    expect(vm.status).toBe(ConstructionStatus.Constructing);
  });

  it("does not run a cancelled foreground completion", () => {
    const { dispatcher, vm, published, hookRuns } = setup();
    vm.construct();
    dispatcher.flushBackground();
    expect(hookRuns()).toBe(1);
    const before = [...published];

    dispatcher.dispose();

    expect(published).toEqual(before);
    expect(vm.status).toBe(ConstructionStatus.Constructing);
  });
});

/**
 * A custom SchedulerLike that queues work until `runNext()` or `flush()`. Like
 * rxjs, a throw from `flush()` unsubscribes every action queued behind it.
 */
class CustomScheduler implements SchedulerLike {
  readonly #queue: Array<{ run: () => void; subscription: Subscription }> = [];

  now(): number {
    return Date.now();
  }

  schedule<T>(
    work: (this: SchedulerAction<T>, state?: T) => void,
    _delay?: number,
    state?: T,
  ): Subscription {
    const subscription = new Subscription();
    const action = subscription as unknown as SchedulerAction<T>;
    this.#queue.push({ run: () => work.call(action, state), subscription });
    return subscription;
  }

  /** Run the next queued action. */
  runNext(): void {
    const next = this.#queue.shift();
    if (next === undefined || next.subscription.closed) return;
    try {
      next.run();
    } finally {
      next.subscription.unsubscribe();
    }
  }

  flush(): void {
    while (this.#queue.length > 0) {
      try {
        this.runNext();
      } catch (error) {
        this.cancel(false);
        throw error;
      }
    }
  }

  /** Unsubscribe every queued action, marking this scheduler first if `mark`. */
  cancel(mark: boolean): void {
    if (mark) markSchedulerCancelled(this);
    for (let next = this.#queue.shift(); next !== undefined; next = this.#queue.shift()) {
      next.subscription.unsubscribe();
    }
  }
}

describe("a custom scheduler and markSchedulerCancelled", () => {
  function setup(hooks: Hooks = {}) {
    const scheduler = new CustomScheduler();
    const hub = new MessageHub();
    let hookRuns = 0;
    const vm = backgroundVM({ foreground: scheduler, background: scheduler }, hub, "vm", {
      construct: () => {
        hookRuns++;
        hooks.construct?.();
      },
    });
    const published: ConstructionStatus[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof ConstructionStatusChangedMessage && message.sender === vm) {
        published.push(message.status);
      }
    });
    return { scheduler, vm, published, hookRuns: () => hookRuns };
  }

  it("runs no VMx hook and publishes no status for work that a marked cancel drops", () => {
    const { scheduler, vm, published, hookRuns } = setup();
    vm.construct();
    const before = [...published];

    scheduler.cancel(true);

    expect(hookRuns()).toBe(0);
    expect(published).toEqual(before);
    expect(vm.status).toBe(ConstructionStatus.Constructing);
  });

  it("still reports a failure that happened before a marked cancel", async () => {
    const reports = captureRxUnhandledErrors();
    const { scheduler, vm, published } = setup({
      construct: () => {
        throw new Error("hook failed");
      },
    });
    vm.construct();
    scheduler.runNext();
    const before = [...published];

    scheduler.cancel(true);

    expect(published).toEqual(before);
    expect(reports).toEqual([]);
    await afterReports();
    expect(messagesOf(reports)).toEqual(["hook failed"]);
  });

  it("settles a VM whose action a flush error dropped on a scheduler that did not mark itself", () => {
    const { scheduler, vm, hookRuns } = setup();
    queueThrow(scheduler, "foreign failed");
    vm.construct();

    expect(() => scheduler.flush()).toThrow("foreign failed");

    expect(hookRuns()).toBe(1);
    expectSettled(vm, ConstructionStatus.Constructed);
  });
});
