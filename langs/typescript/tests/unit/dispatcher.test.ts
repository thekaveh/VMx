// Unit tests for RxDispatcher — factory methods.
//
// NULL-002 covers NullDispatcher; this file covers the concrete RxDispatcher
// factories (`immediate()` and `default()`) which were otherwise only
// exercised transitively through e2e flows.

import { describe, expect, it } from "vitest";
import { asapScheduler, queueScheduler } from "rxjs";

import { RxDispatcher } from "../../src/services/dispatcher.js";

describe("RxDispatcher factories", () => {
  it("immediate() pairs queueScheduler on both foreground and background", () => {
    const dispatcher = RxDispatcher.immediate();
    expect(dispatcher.foreground).toBe(queueScheduler);
    expect(dispatcher.background).toBe(queueScheduler);
  });

  it("default() pairs queueScheduler (fg) with asapScheduler (bg)", () => {
    const dispatcher = RxDispatcher.default();
    expect(dispatcher.foreground).toBe(queueScheduler);
    expect(dispatcher.background).toBe(asapScheduler);
  });

  it("constructor accepts custom scheduler pairs", () => {
    const dispatcher = new RxDispatcher(asapScheduler, queueScheduler);
    expect(dispatcher.foreground).toBe(asapScheduler);
    expect(dispatcher.background).toBe(queueScheduler);
  });
});
