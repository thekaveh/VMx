// Regressions for the disposed-child and Destructing selection rules (spec/02
// §6, spec/06 §4.3 rules 2, 8 and 9; ADR-0188, ADR-0189; #1317, #1383, #1425).

import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  ComponentVMBase,
  ComponentVMOf,
  CompositeVM,
  ConstructionStatus as S,
  ForwardingComponentVM,
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
}

function deferredServices() {
  const fg = new DeferredScheduler();
  const bg = new DeferredScheduler();
  const dispatcher = new RxDispatcher(
    fg as unknown as SchedulerLike,
    bg as unknown as SchedulerLike,
  );
  return { fg, bg, dispatcher, hub: new MessageHub() };
}

describe("a container walk that waits for a child disposed meanwhile (ADR-0189)", () => {
  for (const kind of ["composite", "group"] as const) {
    for (const construct of [true, false]) {
      it(`${kind} ${construct ? "construct" : "destruct"} settles at the target`, () => {
        const bg = new DeferredScheduler();
        const dispatcher = new RxDispatcher(
          RxDispatcher.immediate().foreground,
          bg as unknown as SchedulerLike,
        );
        const hub = new MessageHub();
        const slow = ComponentVM.builder()
          .name("slow").services(hub, dispatcher).background(true).build();
        const fast = ComponentVM.builder().name("fast").services(hub, dispatcher).build();
        const box: ComponentVMBase =
          kind === "composite"
            ? CompositeVM.builder<ComponentVM>()
                .name("box").services(hub, dispatcher).children(() => [slow, fast]).build()
            : GroupVM.builder<ComponentVM>()
                .name("box").services(hub, dispatcher).children(() => [slow, fast]).build();
        if (!construct) {
          box.construct();
          bg.runAll();
          expect(box.status).toBe(S.Constructed);
          box.destruct();
        } else {
          box.construct();
        }
        expect(box.status).toBe(construct ? S.Constructing : S.Destructing);

        slow.dispose();
        bg.runAll();

        expect(slow.status).toBe(S.Disposed);
        expect(box.status).toBe(construct ? S.Constructed : S.Destructed);
        expect(fast.status).toBe(construct ? S.Constructed : S.Destructed);
      });
    }
  }
});

describe("an asynchronous selection delivered while Destructing (ADR-0188)", () => {
  it("is dropped, so destruct() ends with Current null", () => {
    const { fg, bg, dispatcher, hub } = deferredServices();
    const a = ComponentVM.builder().name("a").services(hub, dispatcher).build();
    const slow = ComponentVM.builder()
      .name("slow").services(hub, dispatcher).background(true).build();
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [a, slow])
      .asyncSelection(true)
      .build();
    p.construct();
    bg.runAll();
    fg.runAll();
    expect(p.status).toBe(S.Constructed);

    p.current = a;
    p.destruct();
    expect(p.status).toBe(S.Destructing);
    fg.runAll();

    expect(p.current).toBeNull();
    expect(a.isCurrent).toBe(false);
    bg.runAll();
    fg.runAll();
    expect(p.status).toBe(S.Destructed);
    expect(p.current).toBeNull();
  });
});

describe("the dispose clear (ADR-0189)", () => {
  it("clears a forwarding decorator that is Current when it is disposed", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const inner = ComponentVMOf.builder<string>()
      .name("inner").model("m").services(hub, dispatcher).build();
    const wrapper = new ForwardingComponentVM(inner);
    const other = ComponentVM.builder().name("other").services(hub, dispatcher).build();
    const changes: (ComponentVMBase | null)[] = [];
    const p = CompositeVM.builder<ComponentVMBase>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [wrapper, other])
      .onCurrentChanged((vm) => changes.push(vm))
      .build();
    p.construct();
    p.current = wrapper;
    changes.length = 0;

    wrapper.dispose();

    expect(inner.status).toBe(S.Disposed);
    expect(p.current).toBeNull();
    expect(wrapper.isCurrent).toBe(false);
    expect(changes).toEqual([null]);
  });

  it("refuses a reselection of the disposed child from onCurrentChanged(null)", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const a = ComponentVM.builder().name("a").services(hub, dispatcher).build();
    const b = ComponentVM.builder().name("b").services(hub, dispatcher).build();
    let p: CompositeVM<ComponentVM> | null = null;
    p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [a, b])
      .onCurrentChanged((vm) => {
        if (vm === null) (p as CompositeVM<ComponentVM>).current = a;
      })
      .build();
    const composite = p;
    composite.construct();
    composite.current = a;

    expect(() => a.dispose()).toThrow(/not a member/);

    expect(a.status).toBe(S.Disposed);
    expect(composite.current).toBeNull();
    expect(a.isCurrent).toBe(false);
  });

  it("does not clear a child that is no longer Current", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const a = ComponentVM.builder().name("a").services(hub, dispatcher).build();
    const b = ComponentVM.builder().name("b").services(hub, dispatcher).build();
    const changes: (ComponentVM | null)[] = [];
    const p = CompositeVM.builder<ComponentVM>()
      .name("p")
      .services(hub, dispatcher)
      .children(() => [a, b])
      .onCurrentChanged((vm) => changes.push(vm))
      .build();
    p.construct();
    p.current = b;
    changes.length = 0;

    a.dispose();

    expect(p.current).toBe(b);
    expect(changes).toEqual([]);
  });
});
