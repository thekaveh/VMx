// Unit tests for RxDispatcher — factory methods.
//
// NULL-002 covers NullDispatcher; this file covers the concrete RxDispatcher
// factories (`immediate()` and `default()`) which were otherwise only
// exercised transitively through e2e flows.

import { describe, expect, it } from "vitest";
import { asapScheduler, asyncScheduler, queueScheduler } from "rxjs";

import { RxDispatcher } from "../../src/services/dispatcher.js";

describe("RxDispatcher factories", () => {
  it("immediate() pairs queueScheduler on both foreground and background", () => {
    const dispatcher = RxDispatcher.immediate();
    expect(dispatcher.foreground).toBe(queueScheduler);
    expect(dispatcher.background).toBe(queueScheduler);
  });

  it("default() pairs queueScheduler (fg) with asyncScheduler (bg)", () => {
    // VMX-087: background is a true macrotask (asyncScheduler), not an
    // asapScheduler microtask that would drain before timers / paint / I-O.
    const dispatcher = RxDispatcher.default();
    expect(dispatcher.foreground).toBe(queueScheduler);
    expect(dispatcher.background).toBe(asyncScheduler);
    expect(dispatcher.background).not.toBe(asapScheduler);
  });

  it("constructor accepts custom scheduler pairs", () => {
    const dispatcher = new RxDispatcher(asapScheduler, queueScheduler);
    expect(dispatcher.foreground).toBe(asapScheduler);
    expect(dispatcher.background).toBe(queueScheduler);
  });
});
