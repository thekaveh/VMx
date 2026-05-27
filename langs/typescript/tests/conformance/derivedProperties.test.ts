// Conformance tests: DPROP-001..012 — derived properties.
// See spec/15-derived-properties.md and ADR-0011.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { BehaviorSubject } from "rxjs";
import { describe, expect, it } from "vitest";

import { deriveFromSources } from "../../src/properties/index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = join(__dirname, "..", "..", "src", "fixtures");

function loadFixture<T = unknown>(filename: string): T {
  const raw = readFileSync(join(FIXTURES_DIR, filename), "utf-8");
  return JSON.parse(raw) as T;
}

describe("DPROP-001", () => {
  it("single-source derived value computes on construction", () => {
    const s1 = new BehaviorSubject<number>(10);
    const dp = deriveFromSources<number>([s1], (...vs) =>
      (vs[0] as number) * 2,
    );
    expect(dp.value).toBe(20);
    dp.dispose();
  });
});

describe("DPROP-002", () => {
  it("source change triggers recompute", () => {
    const s1 = new BehaviorSubject<number>(10);
    const dp = deriveFromSources<number>([s1], (...vs) =>
      (vs[0] as number) * 2,
    );
    s1.next(5);
    expect(dp.value).toBe(10);
    dp.dispose();
  });
});

describe("DPROP-003", () => {
  it("two-source derived value", () => {
    const s1 = new BehaviorSubject<number>(3);
    const s2 = new BehaviorSubject<number>(4);
    const dp = deriveFromSources<number>(
      [s1, s2],
      (a, b) => (a as number) + (b as number),
    );
    expect(dp.value).toBe(7);
    s2.next(6);
    expect(dp.value).toBe(9);
    dp.dispose();
  });
});

describe("DPROP-004", () => {
  it("five-source derived value (spec minimum)", () => {
    const subjects: BehaviorSubject<number>[] = [];
    for (let i = 0; i < 5; i++) subjects.push(new BehaviorSubject(i + 1));
    const dp = deriveFromSources<number>(subjects, (...vs) =>
      (vs as number[]).reduce((a, b) => a + b, 0),
    );
    expect(dp.value).toBe(15);
    dp.dispose();
  });
});

describe("DPROP-005", () => {
  it("mutation of any source recomputes", () => {
    const subjects: BehaviorSubject<number>[] = [];
    for (let i = 0; i < 5; i++) subjects.push(new BehaviorSubject(i + 1));
    const dp = deriveFromSources<number>(subjects, (...vs) =>
      (vs as number[]).reduce((a, b) => a + b, 0),
    );
    subjects[2]!.next(30);
    expect(dp.value).toBe(1 + 2 + 30 + 4 + 5);
    dp.dispose();
  });
});

describe("DPROP-006", () => {
  it("default-built derived property is read-only", () => {
    const s1 = new BehaviorSubject<number>(1);
    const dp = deriveFromSources<number>([s1], (...vs) => vs[0] as number);
    for (const v of [0, 1, 42, -7]) {
      expect(dp.canSet(v)).toBe(false);
    }
    dp.dispose();
  });
});

describe("DPROP-007", () => {
  it("validator + write-back enables setValue", () => {
    const s1 = new BehaviorSubject<number>(0);
    const recorder: number[] = [];
    const dp = deriveFromSources<number>([s1], (...vs) => vs[0] as number, {
      canSet: (v) => v > 0,
      setAction: (v) => recorder.push(v),
    });
    dp.setValue(5);
    expect(recorder).toEqual([5]);
    expect(() => dp.setValue(-1)).toThrow();
    expect(recorder).toEqual([5]);
    dp.dispose();
  });
});

describe("DPROP-008", () => {
  it("write-back action receives the value", () => {
    const s1 = new BehaviorSubject<number>(0);
    const recorder: number[] = [];
    const dp = deriveFromSources<number>([s1], (...vs) => vs[0] as number, {
      canSet: () => true,
      setAction: (v) => recorder.push(v),
    });
    dp.setValue(7);
    expect(recorder).toEqual([7]);
    dp.dispose();
  });
});

describe("DPROP-009", () => {
  it("valueChanged emits on recompute", () => {
    const s1 = new BehaviorSubject<number>(1);
    const dp = deriveFromSources<number>([s1], (...vs) => vs[0] as number);
    const observed: number[] = [];
    const sub = dp.valueChanged.subscribe((v) => observed.push(v));
    s1.next(2);
    s1.next(3);
    expect(observed).toEqual([2, 3]);
    sub.unsubscribe();
    dp.dispose();
  });
});

describe("DPROP-010", () => {
  it("valueChanged does not emit when transform output unchanged", () => {
    const s1 = new BehaviorSubject<number>(5);
    const s2 = new BehaviorSubject<number>(5);
    const dp = deriveFromSources<number>(
      [s1, s2],
      (a, b) => (a as number) + (b as number),
    );
    const observed: number[] = [];
    const sub = dp.valueChanged.subscribe((v) => observed.push(v));
    s1.next(3); // 3+5 = 8 → emit
    s2.next(7); // 3+7 = 10 → emit
    expect(observed).toEqual([8, 10]);
    s1.next(3); // 3+7 still 10 → no emit
    expect(observed).toEqual([8, 10]);
    sub.unsubscribe();
    dp.dispose();
  });
});

describe("DPROP-011", () => {
  it("dispose ends subscriptions; valueChanged completes", () => {
    const s1 = new BehaviorSubject<number>(1);
    const dp = deriveFromSources<number>([s1], (...vs) => vs[0] as number);
    const observed: number[] = [];
    let completed = false;
    const sub = dp.valueChanged.subscribe({
      next: (v) => observed.push(v),
      complete: () => {
        completed = true;
      },
    });
    s1.next(2);
    expect(observed).toEqual([2]);
    dp.dispose();
    expect(completed).toBe(true);
    s1.next(3);
    expect(dp.value).toBe(2);
    sub.unsubscribe();
  });
});

type FixtureMutation = [number, unknown];
interface FixtureScenario {
  name: string;
  sources_initial: unknown[];
  transform: string;
  mutations: FixtureMutation[];
  expected_values: unknown[];
}
interface Fixture {
  scenarios: FixtureScenario[];
}

const TRANSFORMS: Record<string, (...vs: unknown[]) => unknown> = {
  sum: (...vs) => (vs as number[]).reduce((a, b) => a + b, 0),
  concat: (...vs) => vs.map((v) => String(v)).join(""),
};

describe("DPROP-012", () => {
  it("derived-property scenarios match fixture", () => {
    const fixture = loadFixture<Fixture>("derived-properties.json");
    for (const scenario of fixture.scenarios) {
      const transform = TRANSFORMS[scenario.transform]!;
      const subjects = scenario.sources_initial.map(
        (v) => new BehaviorSubject<unknown>(v),
      );
      const dp = deriveFromSources<unknown>(subjects, transform);
      const actuals: unknown[] = [dp.value];
      for (const [idx, val] of scenario.mutations) {
        subjects[idx]!.next(val);
        actuals.push(dp.value);
      }
      expect(actuals).toEqual(scenario.expected_values);
      dp.dispose();
    }
  });
});
