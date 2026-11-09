// Replacing the current child (spec/06 §3, §4.2 and §4.3 rule 6; #1219).
//
// An index replacement keeps the replaced child owned and current until its
// commit, which frees the child and clears Current in one step. No container
// can adopt the child while it is still current here, and a failed
// replacement restores it silently. Mirrors the Swift
// CompositeVMMembershipTests and the C# and Python ReplaceAndSelectRace tests.
//
// The asynchronous selectComponent delivery checks Constructed again (spec/06
// §3.1 and §4.3 rule 7; #1220). TypeScript runs on one thread, so a
// synchronous selection has no window between its check and its commit.
//
// A child's select() silently refuses a member that is not Constructed, and
// its asynchronous delivery checks again (spec/05 §6, spec/06 §3.1; #1229).

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { IDispatcher } from "../../src/index.js";

class HookFailed extends Error {}

class DeferredScheduler {
  #work: Array<() => void> = [];

  schedule(work: () => void): { unsubscribe(): void } {
    this.#work.push(work);
    return { unsubscribe() {} };
  }

  runAll(): void {
    while (this.#work.length > 0) {
      const batch = this.#work;
      this.#work = [];
      for (const work of batch) work();
    }
  }
}

const hub = new MessageHub();
const immediate = (): IDispatcher => RxDispatcher.immediate();

function leaf(name: string, onConstruct: () => void = () => {}, dispatcher = immediate()): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).onConstruct(onConstruct).build();
}

function composite(
  children: ComponentVM[],
  options: { changes?: Array<string | null>; dispatcher?: IDispatcher; asyncSelection?: boolean } = {},
): CompositeVM<ComponentVM> {
  return CompositeVM.builder<ComponentVM>()
    .name("composite")
    .services(hub, options.dispatcher ?? immediate())
    .children(() => children)
    .autoConstructOnAdd(true)
    .asyncSelection(options.asyncSelection ?? false)
    .onCurrentChanged((value) => options.changes?.push(value?.name ?? null))
    .build();
}

/**
 * A Constructed composite [a, b] with a current, and a replacement whose
 * construct hook runs inside the replacement's transaction.
 */
function replacementScenario(hook: (a: ComponentVM, sut: CompositeVM<ComponentVM>) => void) {
  const a = leaf("a");
  const b = leaf("b");
  const changes: Array<string | null> = [];
  const sut = composite([a, b], { changes });
  sut.construct();
  sut.current = a;
  changes.length = 0;
  const replacement = leaf("replacement", () => hook(a, sut));
  return { a, b, sut, changes, replacement };
}

function holders(child: ComponentVM, ...composites: Array<CompositeVM<ComponentVM>>) {
  return composites.filter((c) => c.snapshot().includes(child));
}

describe("replacing the current child (#1219)", () => {
  it("lets the replacement hook see the current child still owned and flagged", () => {
    const observed: Array<{ owned: boolean; current: boolean; flag: boolean }> = [];
    const { a, sut, changes, replacement } = replacementScenario((a, sut) => {
      observed.push({ owned: a._parent === sut, current: sut.current === a, flag: a.isCurrent });
    });

    sut.setAt(0, replacement);

    expect(observed).toHaveLength(1);
    expect(observed[0]?.current).toBe(true);
    expect(observed[0]?.owned).toBe(true);
    expect(observed[0]?.flag).toBe(observed[0]?.current);
    expect(sut.current).toBeNull();
    expect(a.isCurrent).toBe(false);
    expect(a._parent).toBeNull();
    expect(changes).toEqual([null]);
  });

  it("does not let the replacement hook adopt and select the replaced current child", () => {
    const other = composite([]);
    other.construct();
    const { a, sut, replacement } = replacementScenario((a) => {
      try {
        other.add(a);
        other.current = a;
      } catch {
        // A refused adoption leaves a where it is.
      }
    });

    sut.setAt(0, replacement);

    expect(sut.current).toBeNull();
    // The commit's clear never resets a selection in another composite (COMP-006).
    expect(a.isCurrent).toBe(other.current === a);
    const holding = holders(a, sut, other);
    expect(holding.length).toBeLessThanOrEqual(1);
    if (holding.length === 1) expect(a._parent).toBe(holding[0]);
  });

  it("leaves the replaced child in exactly one composite after a failed replacement", () => {
    const other = composite([]);
    other.construct();
    const { a, b, sut, replacement } = replacementScenario((a) => {
      try {
        other.add(a);
      } catch {
        // A refused adoption leaves a where it is.
      }
      throw new HookFailed();
    });

    expect(() => sut.setAt(0, replacement)).toThrow(HookFailed);

    const holding = holders(a, sut, other);
    expect(holding).toHaveLength(1);
    expect(a._parent).toBe(holding[0]);
    expect(sut.snapshot()).toEqual([a, b]);
    expect(replacement._parent).toBeNull();
  });

  it("restores the current child silently after a failed replacement", () => {
    const { a, b, sut, changes, replacement } = replacementScenario(() => {
      throw new HookFailed();
    });
    const events: unknown[] = [];
    const properties: string[] = [];
    sut.collectionChanged.subscribe((event) => events.push(event));
    sut.propertyChanged.subscribe((name) => properties.push(name));
    a.propertyChanged.subscribe((name) => properties.push(name));

    expect(() => sut.setAt(0, replacement)).toThrow(HookFailed);

    expect(sut.snapshot()).toEqual([a, b]);
    expect(sut.current).toBe(a);
    expect(a.isCurrent).toBe(true);
    expect(a._parent).toBe(sut);
    expect(events).toEqual([]);
    expect(changes).toEqual([]);
    expect(properties).not.toContain("current");
    expect(properties).not.toContain("isCurrent");
  });
});

describe("the Constructed check of an asynchronous selectComponent (#1220)", () => {
  it("drops a delivery for a child destructed after the call", () => {
    const fg = new DeferredScheduler();
    const dispatcher: IDispatcher = new RxDispatcher(
      fg as unknown as SchedulerLike,
      RxDispatcher.immediate().background,
    );
    const vm = leaf("vm", () => {}, dispatcher);
    const sut = composite([vm], { dispatcher, asyncSelection: true });
    sut.construct();
    fg.runAll();

    sut.selectComponent(vm);
    vm.destruct();
    fg.runAll();

    expect(vm.status).toBe(S.Destructed);
    expect(sut.current).toBeNull();
    expect(vm.isCurrent).toBe(false);
  });

  it("delivers a selection for a child that stays Constructed", () => {
    const fg = new DeferredScheduler();
    const dispatcher: IDispatcher = new RxDispatcher(
      fg as unknown as SchedulerLike,
      RxDispatcher.immediate().background,
    );
    const vm = leaf("vm", () => {}, dispatcher);
    const sut = composite([vm], { dispatcher, asyncSelection: true });
    sut.construct();
    fg.runAll();

    sut.selectComponent(vm);
    fg.runAll();

    expect(sut.current).toBe(vm);
    expect(vm.isCurrent).toBe(true);
  });
});

describe("select() on a member that is not Constructed (#1229)", () => {
  function queued() {
    const fg = new DeferredScheduler();
    const dispatcher: IDispatcher = new RxDispatcher(
      fg as unknown as SchedulerLike,
      RxDispatcher.immediate().background,
    );
    const a = leaf("a", () => {}, dispatcher);
    const sut = composite([a], { dispatcher, asyncSelection: true });
    sut.construct();
    fg.runAll();
    return { a, sut, fg };
  }

  it("selects nothing for a destructed member", () => {
    const a = leaf("a");
    const changes: Array<string | null> = [];
    const sut = composite([a], { changes });
    sut.construct();
    a.destruct();

    a.select();

    expect(sut.current).toBeNull();
    expect(a.isCurrent).toBe(false);
    expect(changes).toEqual([]);
  });

  it("selects nothing for a destructed member with asynchronous selection", () => {
    const { a, sut, fg } = queued();
    a.destruct();

    a.select();
    fg.runAll();

    expect(sut.current).toBeNull();
    expect(a.isCurrent).toBe(false);
  });

  it("drops a delivery for a member destructed after the call", () => {
    const { a, sut, fg } = queued();

    a.select();
    a.destruct();
    fg.runAll();

    expect(a.status).toBe(S.Destructed);
    expect(sut.current).toBeNull();
    expect(a.isCurrent).toBe(false);
  });

  it("is silent inside the caller's own transaction too (ADR-0188)", () => {
    const a = leaf("a");
    const sut = composite([a]);
    sut.construct();
    a.destruct();
    let caught: unknown = null;
    const replacement = leaf("replacement", () => {
      try {
        a.select();
      } catch (error) {
        caught = error;
      }
    });
    const b = leaf("b");
    sut.add(b);
    sut.setAt(1, replacement);

    expect(caught).toBeNull();
    expect(sut.current).toBeNull();
  });

  it("makes a Constructed member current", () => {
    const a = leaf("a");
    const sut = composite([a]);
    sut.construct();

    a.select();

    expect(sut.current).toBe(a);
    expect(a.isCurrent).toBe(true);
  });

  it("makes a Constructed member current with asynchronous selection", () => {
    const { a, sut, fg } = queued();

    a.select();
    fg.runAll();

    expect(sut.current).toBe(a);
    expect(a.isCurrent).toBe(true);
  });
});
