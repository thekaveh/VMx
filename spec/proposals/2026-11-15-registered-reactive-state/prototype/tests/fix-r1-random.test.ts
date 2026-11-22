/**
 * A seeded randomized consistency test for the fix-round-1 machinery: reaction starts as drain entries, the R9.2
 * skip rule, producer flushes (R9.8), re-entrant writes by hub observers, change scopes and lifecycle transitions.
 *
 * After every top-level operation (the drain is empty) it checks:
 * 1. every registered computed of every activated view-model equals the same formula evaluated on the raw state;
 * 2. every computed whose value changed during the operation was announced on the hub;
 * 3. every effect of a constructed view-model saw the latest value of what it reads, and its write converged;
 * 4. no error reached the stream-fed route.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, ConstructionStatus, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, untracked } from "../src/index.js";
import { base, type Services, services, streamFed } from "./support.js";

function prng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

class Cell extends ComponentVM {
  declare a: number;
  declare b: number;
  declare mirror: number;
  readonly source: Cell | null;
  lastSeen: number | null = null;
  runs = 0;

  constructor(s: Services, index: number, source: Cell | null) {
    super(base(s, `cell${String(index)}`));
    this.source = source;
    this.observable({ a: 0, b: 0, mirror: 0 });
    this.computed("c1", "c2", "c3", "c4", "c5");
    this.effect(() => {
      this.runs += 1;
      const value = this.c4;
      this.lastSeen = value;
      // A write by the effect itself (bounded: it converges in one step).
      this.mirror = value % 7;
    });
  }

  get c1(): number {
    return this.a + this.b;
  }
  get c2(): number {
    return this.c1 * 2;
  }
  get c3(): number {
    // A dynamic dependency, across view-models when a is even.
    return this.a % 2 === 0 && this.source !== null ? this.source.c1 : this.b;
  }
  get c4(): number {
    return this.c2 + this.c3;
  }
  get c5(): number {
    return this.mirror + this.c1;
  }

  ping(): void {
    this._notifyPropertyChanged("ping");
  }
}

interface Expected {
  readonly c1: number;
  readonly c2: number;
  readonly c3: number;
  readonly c4: number;
  readonly c5: number;
}

function expected(cell: Cell): Expected {
  return untracked(() => {
    const raw = (vm: Cell): { a: number; b: number; mirror: number } => ({ a: vm.a, b: vm.b, mirror: vm.mirror });
    const own = raw(cell);
    const c1 = own.a + own.b;
    const c2 = c1 * 2;
    const source = cell.source === null ? null : raw(cell.source);
    const c3 = own.a % 2 === 0 && source !== null ? source.a + source.b : own.b;
    return { c1, c2, c3, c4: c2 + c3, c5: own.mirror + c1 };
  });
}

const NAMES = ["c1", "c2", "c3", "c4", "c5"] as const;

function snapshot(cells: readonly Cell[]): Map<string, number> {
  const values = new Map<string, number>();
  for (const cell of cells) {
    const e = expected(cell);
    for (const name of NAMES) values.set(`${cell.name}.${name}`, e[name]);
  }
  return values;
}

function runScenario(seed: number, steps: number): void {
  const random = prng(seed);
  const pick = (n: number): number => Math.floor(random() * n);
  const s = services();
  const cells: Cell[] = [];
  for (let i = 0; i < 5; i += 1) cells.push(new Cell(s, i, i === 0 ? null : (cells[pick(i)] ?? null)));
  for (const cell of cells) activate(cell);
  const announced = new Set<string>();
  let budget = 0;
  s.hub.messages.subscribe((m) => {
    if (!(m instanceof PropertyChangedMessage)) return;
    announced.add(`${m.senderName}.${m.propertyName}`);
    // Re-entrant work by an observer, bounded per operation: a write of another cell and a direct send.
    if (budget > 0 && m.propertyName === "c2") {
      budget -= 1;
      const target = cells[pick(cells.length)];
      if (target !== undefined && target.status !== ConstructionStatus.Disposed) {
        target.b = pick(4);
        target.ping();
      }
    }
  });
  for (let step = 0; step < steps; step += 1) {
    const before = snapshot(cells);
    announced.clear();
    budget = pick(3);
    const cell = cells[pick(cells.length)];
    if (cell === undefined) continue;
    const roll = random();
    if (roll < 0.45) {
      if (random() < 0.5) cell.a = pick(5);
      else cell.b = pick(5);
    } else if (roll < 0.65) {
      cell.change(() => {
        cell.a = pick(5);
        const other = cells[pick(cells.length)];
        if (other !== undefined) other.b = pick(5);
        cell.b = pick(5);
      });
    } else if (roll < 0.8) {
      if (cell.status === ConstructionStatus.Constructed) cell.destruct();
      else cell.construct();
    } else if (roll < 0.9) {
      cell.reconstruct === undefined || cell.status !== ConstructionStatus.Constructed
        ? cell.construct()
        : cell.reconstruct();
    } else {
      cell.ping();
    }
    const after = snapshot(cells);
    for (const target of cells) {
      const e = expected(target);
      for (const name of NAMES) {
        const key = `${target.name}.${name}`;
        assert.equal(target[name], e[name], `seed ${String(seed)} step ${String(step)}: ${key} is stale`);
        if (before.get(key) !== after.get(key)) {
          assert.ok(announced.has(key), `seed ${String(seed)} step ${String(step)}: ${key} changed but was not announced`);
        }
      }
      if (target.status === ConstructionStatus.Constructed) {
        assert.equal(target.lastSeen, e.c4, `seed ${String(seed)} step ${String(step)}: ${target.name}'s effect missed c4`);
        assert.equal(target.mirror, e.c4 % 7, `seed ${String(seed)} step ${String(step)}: ${target.name}.mirror`);
      }
    }
  }
}

describe("randomized consistency of the fix-round-1 machinery", () => {
  for (const seed of [1, 7, 42, 1234, 99991]) {
    it(`seed ${String(seed)}: 400 operations keep every computed current, announced and every effect converged`, async () => {
      await streamFed();
      configureReactiveDiagnostics({ development: false });
      try {
        runScenario(seed, 400);
      } finally {
        configureReactiveDiagnostics({ development: undefined });
      }
      assert.deepEqual(await streamFed(), []);
    });
  }
});
