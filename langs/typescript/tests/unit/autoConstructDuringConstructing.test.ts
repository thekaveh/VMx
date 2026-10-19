// A container's construct() completes only when every child has reached
// Constructed (spec/02-lifecycle.md §6). With autoConstructOnAdd(true), a child
// added while the container is still Constructing (waiting on a background
// child) is constructed at add time and joined by the child walk, so the
// container never reports Constructed with an unconstructed added child.
// Mirrors the C# and Python `auto construct during constructing` tests.

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  ConstructionStatus as S,
  GroupVM,
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

  /** Runs the oldest queued work only. */
  runFirst(): void {
    this.#work.shift()?.();
  }

  /** Runs the newest queued work only. */
  runLast(): void {
    this.#work.pop()?.();
  }
}

interface Container {
  readonly status: S;
  construct(): void;
  add(child: ComponentVM): void;
}

function setup(kind: "composite" | "group", autoConstruct = true) {
  const bg = new DeferredScheduler();
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    bg as unknown as SchedulerLike,
  );
  const hub = new MessageHub();
  const child = (
    name: string,
    opts: { background?: boolean; onConstruct?: () => void } = {},
  ): ComponentVM =>
    ComponentVM.builder()
      .name(name)
      .services(hub, dispatcher)
      .background(opts.background ?? false)
      .onConstruct(opts.onConstruct ?? (() => {}))
      .build();
  const first = child("first", { background: true });
  const root: Container =
    kind === "composite"
      ? CompositeVM.builder<ComponentVM>()
          .name("root")
          .services(hub, dispatcher)
          .children(() => [first])
          .autoConstructOnAdd(autoConstruct)
          .build()
      : GroupVM.builder<ComponentVM>()
          .name("root")
          .services(hub, dispatcher)
          .children(() => [first])
          .autoConstructOnAdd(autoConstruct)
          .build();
  return { bg, child, first, root };
}

describe.each(["composite", "group"] as const)(
  "%s auto-construct-on-add while Constructing",
  (kind) => {
    it("constructs a foreground child added during the background wait", () => {
      const { bg, child, root } = setup(kind);
      root.construct();
      expect(root.status).toBe(S.Constructing);

      const late = child("late");
      root.add(late);
      expect(late.status).toBe(S.Constructed);

      bg.runAll();
      expect(root.status).toBe(S.Constructed);
      expect(late.status).toBe(S.Constructed);
    });

    it("waits for a background child added during the background wait", () => {
      const { bg, child, first, root } = setup(kind);
      root.construct();

      const late = child("late", { background: true });
      root.add(late);
      expect(late.status).toBe(S.Constructing);

      bg.runLast(); // late settles before the original child
      expect(late.status).toBe(S.Constructed);
      expect(root.status).toBe(S.Constructing);
      bg.runAll();
      expect(first.status).toBe(S.Constructed);
      expect(root.status).toBe(S.Constructed);
    });

    it("stays Constructing until a late background child settles", () => {
      const { bg, child, first, root } = setup(kind);
      root.construct();
      const late = child("late", { background: true });
      root.add(late);

      bg.runFirst(); // only the original child settles
      expect(first.status).toBe(S.Constructed);
      expect(late.status).toBe(S.Constructing);
      expect(root.status).toBe(S.Constructing);
      bg.runAll();
      expect(late.status).toBe(S.Constructed);
      expect(root.status).toBe(S.Constructed);
    });

    it("rolls back when a late background child fails, without re-running it", () => {
      const { bg, child, root } = setup(kind);
      root.construct();
      let runs = 0;
      const late = child("late", {
        background: true,
        onConstruct: () => {
          runs += 1;
          throw new Error("late failed");
        },
      });
      root.add(late);
      // The late child fails first; its failure surfaces from its own work.
      expect(() => { bg.runLast(); }).toThrow("late failed");
      expect(late.status).toBe(S.Destructed);
      // The walk joins the failed child: it rolls the root back without
      // re-running the hook or surfacing the failure a second time.
      expect(() => { bg.runAll(); }).not.toThrow();
      expect(runs).toBe(1);
      expect(root.status).toBe(S.Destructed);
    });

    it("leaves a child added during Constructing alone without auto-construct", () => {
      const { bg, child, root } = setup(kind, false);
      root.construct();
      const late = child("late");
      root.add(late);
      bg.runAll();
      expect(root.status).toBe(S.Constructed);
      expect(late.status).toBe(S.Destructed);
    });
  },
);
