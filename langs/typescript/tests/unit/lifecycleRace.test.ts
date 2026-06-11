// Regression tests for dispose races against scheduled background work
// (spec/02-lifecycle.md invariant 3: Disposed is terminal). Mirrors the C#
// ComponentVMLifecycleRaceTests and the Python sibling.

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

class DeferredScheduler {
  readonly #work: Array<() => void> = [];

  schedule(work: () => void): { unsubscribe(): void } {
    this.#work.push(work);
    return { unsubscribe() {} };
  }

  runAll(): void {
    for (const work of this.#work) work();
  }
}

describe("ComponentVM – dispose during in-flight background construct", () => {
  it("does not resurrect the VM or publish post-dispose status messages", () => {
    const bg = new DeferredScheduler();
    const dispatcher = new RxDispatcher(
      RxDispatcher.immediate().foreground,
      bg as unknown as SchedulerLike,
    );
    const hub = new MessageHub();
    const vm = ComponentVM.builder()
      .name("bgvm")
      .services(hub, dispatcher)
      .background(true)
      .build();

    const statuses: ConstructionStatus[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof ConstructionStatusChangedMessage) statuses.push(m.status);
    });

    vm.construct(); // Constructing emitted; work deferred
    vm.dispose(); // terminal before the background work runs
    bg.runAll(); // the scheduled work must now no-op

    expect(vm.status).toBe(ConstructionStatus.Disposed);
    expect(statuses).not.toContain(ConstructionStatus.Constructed);
    expect(statuses[statuses.length - 1]).toBe(ConstructionStatus.Disposed);
  });
});
