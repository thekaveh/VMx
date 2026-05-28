// Conformance tests: CAP-021 — IFilterable<T> capability contract surface.
// See spec/14-capabilities.md §Filterable and ADR-0022.

import { describe, expect, it } from "vitest";

import type { IFilterable } from "../../src/capabilities/index.js";

describe("CAP-021", () => {
  it("IFilterable<T> contract: settable filter predicate and canFilter() decision", () => {
    class TestFilterable<T> implements IFilterable<T> {
      filter: ((item: T) => boolean) | null = null;
      canFilter(): boolean {
        return true;
      }
    }

    const sut = new TestFilterable<number>();
    expect(sut.filter).toBeNull();
    expect(sut.canFilter()).toBe(true);

    const p = (x: number) => x > 0;
    sut.filter = p;
    expect(sut.filter).toBe(p);

    sut.filter = null;
    expect(sut.filter).toBeNull();
  });

  it("IFilterable<T>: setting filter to null clears the filter", () => {
    class TestFilterable<T> implements IFilterable<T> {
      filter: ((item: T) => boolean) | null = null;
      canFilter(): boolean {
        return this.filter !== null;
      }
    }

    const sut = new TestFilterable<string>();
    sut.filter = (s: string) => s.length > 0;
    expect(sut.filter).not.toBeNull();
    expect(sut.canFilter()).toBe(true);

    sut.filter = null;
    expect(sut.filter).toBeNull();
    expect(sut.canFilter()).toBe(false);
  });
});
