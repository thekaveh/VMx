/**
 * ReactDispatcher — adapter coverage test (Phase 5.c).
 *
 * Verifies the `foreground` and `background` SchedulerLike fields are set
 * to rxjs's asap/async schedulers. The dispatcher carries no runtime logic
 * beyond exposing those two scheduler references, so a single instantiation
 * + identity check is sufficient.
 */
import { asapScheduler, asyncScheduler } from "rxjs";
import { describe, expect, it } from "vitest";

import { ReactDispatcher } from "../../../src/views/adapter/ReactDispatcher.js";

describe("ReactDispatcher", () => {
  it("exposes asapScheduler as foreground", () => {
    const d = new ReactDispatcher();
    expect(d.foreground).toBe(asapScheduler);
  });

  it("exposes asyncScheduler as background", () => {
    const d = new ReactDispatcher();
    expect(d.background).toBe(asyncScheduler);
  });
});
