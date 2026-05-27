// Conformance tests: LOC-001..003 — localization hooks.
// See spec/17-localization.md and ADR-0019.

import { describe, expect, it } from "vitest";

import { type ILocalizer, NullLocalizer } from "../../src/index.js";

class FakeLocalizer implements ILocalizer {
  localize(key: string): string {
    return key === "greeting" ? "hello" : key;
  }
}

class XLocalizer implements ILocalizer {
  localize(key: string): string {
    return "X:" + key;
  }
}

describe("LOC-001", () => {
  it("ILocalizer.localize returns a string", () => {
    const loc: ILocalizer = new FakeLocalizer();
    expect(loc.localize("greeting")).toBe("hello");
  });
});

describe("LOC-002", () => {
  it("NullLocalizer.localize returns the key verbatim", () => {
    const loc = NullLocalizer.INSTANCE;
    expect(loc.localize("some-key")).toBe("some-key");
    expect(loc.localize("some-key", ["a", "b"])).toBe("some-key");
  });
});

describe("LOC-003", () => {
  it("Custom localizer can substitute the null variant", () => {
    const loc: ILocalizer = new XLocalizer();
    expect(loc.localize("foo")).toBe("X:foo");
  });
});
