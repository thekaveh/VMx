// Unit tests for the typed-arity DerivedProperty factories (ADR-0035 §2 DP2)
// — added to TS after the maintenance audit found the surface missing while
// ADR-0035 and the Python docstrings claimed it existed.

import { describe, expect, it } from "vitest";
import { BehaviorSubject } from "rxjs";
import { fromFive, fromMany, fromOne, fromSources, fromTwo } from "../../src/index.js";

describe("DerivedProperty typed-arity factories", () => {
  it("fromOne maps a single typed source", () => {
    const s = new BehaviorSubject(2);
    const dp = fromOne(s, (v) => v * 10);
    expect(dp.value).toBe(20);
    s.next(3);
    expect(dp.value).toBe(30);
    dp.dispose();
  });

  it("fromTwo combines two typed sources", () => {
    const a = new BehaviorSubject(2);
    const b = new BehaviorSubject("x");
    const dp = fromTwo(a, b, (n, s) => s.repeat(n));
    expect(dp.value).toBe("xx");
    a.next(3);
    expect(dp.value).toBe("xxx");
    dp.dispose();
  });

  it("fromFive combines five typed sources", () => {
    const s1 = new BehaviorSubject(1);
    const s2 = new BehaviorSubject(2);
    const s3 = new BehaviorSubject(3);
    const s4 = new BehaviorSubject(4);
    const s5 = new BehaviorSubject(5);
    const dp = fromFive(s1, s2, s3, s4, s5, (a, b, c, d, e) => a + b + c + d + e);
    expect(dp.value).toBe(15);
    s5.next(50);
    expect(dp.value).toBe(60);
    dp.dispose();
  });

  it("fromMany is an alias of fromSources", () => {
    expect(fromMany).toBe(fromSources);
  });
});
