/**
 * resolveHub — coverage for the missing-hub error path (Phase 5.c).
 */
import { describe, expect, it } from "vitest";

import { resolveHub } from "../../../src/views/adapter/_hubAccessor.js";

describe("resolveHub", () => {
  it("throws a clear error when the VM has no `hub` getter", () => {
    class Bogus {}
    expect(() => resolveHub(new Bogus())).toThrow(/does not expose a public 'hub'/);
  });

  it("returns the hub when present", () => {
    const stubHub = { messages: { subscribe: () => ({ unsubscribe: () => {} }) } };
    const vm = { hub: stubHub };
    expect(resolveHub(vm)).toBe(stubHub);
  });
});
