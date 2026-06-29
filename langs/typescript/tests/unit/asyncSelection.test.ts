/**
 * VMX-086 regression — asyncSelection genuinely defers, and the TOCTOU re-check
 * guard in compositeVMBase._applyCurrentChange actually fires.
 *
 * Every conformance test wires `RxDispatcher.immediate()`, whose foreground is
 * the synchronous `queueScheduler` — so `asyncSelection:true` collapsed to an
 * inline application and the deferred-delivery TOCTOU guard was dead code. These
 * tests use a genuinely-async foreground (rxjs TestScheduler) so both paths are
 * exercised.
 */
import { describe, expect, it } from "vitest";
import { queueScheduler } from "rxjs";
import { TestScheduler } from "rxjs/testing";
import {
  CompositeVM,
  ComponentVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

function makeTestScheduler(): TestScheduler {
  return new TestScheduler((actual, expected) => {
    expect(actual).toEqual(expected);
  });
}

function makeComposite(foreground: TestScheduler): {
  composite: CompositeVM<ComponentVM>;
  a: ComponentVM;
  b: ComponentVM;
} {
  const hub = new MessageHub();
  // Foreground = async TestScheduler; background irrelevant here.
  const disp = new RxDispatcher(foreground, queueScheduler);
  const a = ComponentVM.builder().name("a").services(hub, disp).build();
  const b = ComponentVM.builder().name("b").services(hub, disp).build();
  const composite = CompositeVM.builder<ComponentVM>()
    .name("comp")
    .services(hub, disp)
    .asyncSelection(true)
    .children(() => [a, b])
    .build();
  composite.construct();
  return { composite, a, b };
}

describe("VMX-086: asyncSelection defers and the TOCTOU guard fires", () => {
  it("applies the current change only after the foreground scheduler advances", () => {
    const foreground = makeTestScheduler();
    const { composite, a } = makeComposite(foreground);

    composite.current = a;

    // With a truly-async foreground the application is deferred — the no-op
    // that immediate()'s synchronous queueScheduler had been masking.
    expect(
      composite.current,
      "async selection must defer the current change until the fg scheduler advances",
    ).toBeNull();
    expect(a.isCurrent).toBe(false);

    foreground.flush();

    expect(composite.current).toBe(a);
    expect(a.isCurrent).toBe(true);
  });

  it("drops a deferred selection whose target left the collection first (TOCTOU guard)", () => {
    const foreground = makeTestScheduler();
    const { composite, a } = makeComposite(foreground);

    composite.current = a; // deferred onto the foreground scheduler
    composite.remove(a); // a leaves before the deferred application runs

    foreground.flush(); // _applyCurrentChange now sees a is no longer a member

    // The previously-dead TOCTOU re-check drops the stale selection, upholding
    // "a non-null current is always a member of the children collection".
    expect(composite.current).toBeNull();
    expect(a.isCurrent).toBe(false);
  });
});
