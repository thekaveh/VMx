/**
 * The `current(selector)` input is the live membership (spec/06 §3.2,
 * ADR-0218 rule 2, #1312). A child added while the construct walk waits is
 * in the input, and the selector may pick it.
 *
 * TypeScript runs on one thread: the background member settles when the test
 * drains the queued background scheduler.
 */
import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

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

function fixture() {
  const bg = new DeferredScheduler();
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const child = (name: string, background: boolean): ComponentVM =>
    ComponentVM.builder().name(name).services(hub, dispatcher).background(background).build();
  return { bg, hub, dispatcher, child };
}

describe("COMP-053", () => {
  it("passes the live membership, so the selector can pick a late child", () => {
    const { bg, hub, dispatcher, child } = fixture();
    const a = child("a", true);
    const l = child("l", false);
    const inputs: ComponentVM[][] = [];
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [a])
      .autoConstructOnAdd(true)
      .current((xs) => {
        const input = [...xs];
        inputs.push(input);
        return input.includes(l) ? l : null;
      })
      .build();

    p.construct();
    expect(p.status).toBe(S.Constructing);
    p.add(l);
    expect(() => bg.runAll()).not.toThrow();

    expect(p.status).toBe(S.Constructed);
    expect(inputs).toHaveLength(1);
    expect(inputs[0]).toContain(a);
    expect(inputs[0]).toContain(l);
    expect(p.current).toBe(l);
    expect(l.isCurrent).toBe(true);
  });

  it("ignores a pick that is not a member", () => {
    const { bg, hub, dispatcher, child } = fixture();
    const a = child("a", true);
    const stranger = child("stranger", false);
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [a])
      .current(() => stranger)
      .build();

    p.construct();
    expect(() => bg.runAll()).not.toThrow();

    expect(p.status).toBe(S.Constructed);
    expect(p.current).toBeNull();
    expect(stranger.isCurrent).toBe(false);
  });
});
