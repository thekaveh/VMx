// Stress run (informative): the randomized consistency scenario of tests/fix-r1-random.test.ts with more
// seeds and more operations, plus fix-round-2 pressure: writes made by observers of status messages (publications
// that hold the drain), disposals made by observers, and members.
// Run: NODE_ENV=test node bench/random-r2.mjs [seeds] [steps]
import assert from "node:assert/strict";
import { ComponentVM, ConstructionStatus, ConstructionStatusChangedMessage, MessageHub, PropertyChangedMessage, RxDispatcher } from "@thekaveh/vmx";
import { config } from "rxjs";
import { activate, configureReactiveDiagnostics, untracked } from "../build/src/index.js";

const unhandled = [];
config.onUnhandledError = (error) => unhandled.push(error);
configureReactiveDiagnostics({ development: false });

function prng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

class Cell extends ComponentVM {
  constructor(s, index, source) {
    super({ name: `cell${index}`, hint: "", hub: s.hub, dispatcher: s.dispatcher });
    this.source = source;
    this.lastSeen = null;
    this.observable({ a: 0, b: 0, mirror: 0 });
    this.computed("c1", "c2", "c3", "c4", "c5");
    this.effect(() => {
      const value = this.c4;
      this.lastSeen = value;
      this.mirror = value % 7;
    });
  }
  get c1() { return this.a + this.b; }
  get c2() { return this.c1 * 2; }
  get c3() { return this.a % 2 === 0 && this.source !== null ? this.source.c1 : this.b; }
  get c4() { return this.c2 + this.c3; }
  get c5() { return this.mirror + this.c1; }
  ping() { this._notifyPropertyChanged("ping"); }
}

const NAMES = ["c1", "c2", "c3", "c4", "c5"];

function expected(cell) {
  return untracked(() => {
    const own = { a: cell.a, b: cell.b, mirror: cell.mirror };
    const c1 = own.a + own.b;
    const c2 = c1 * 2;
    const src = cell.source;
    const live = src !== null && src.status !== ConstructionStatus.Disposed;
    const c3 = own.a % 2 === 0 && src !== null ? (live ? src.a + src.b : src.c1) : own.b;
    return { c1, c2, c3, c4: c2 + c3, c5: own.mirror + c1 };
  });
}

function run(seed, steps) {
  const random = prng(seed);
  const pick = (n) => Math.floor(random() * n);
  const s = { hub: new MessageHub(), dispatcher: RxDispatcher.immediate() };
  const cells = [];
  for (let i = 0; i < 6; i += 1) cells.push(new Cell(s, i, i === 0 ? null : cells[pick(i)] ?? null));
  for (const cell of cells) activate(cell);
  const announced = new Set();
  let budget = 0;
  let disposeBudget = 0;
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage) announced.add(`${m.senderName}.${m.propertyName}`);
    if (budget > 0 && (m instanceof ConstructionStatusChangedMessage || (m instanceof PropertyChangedMessage && m.propertyName === "c2"))) {
      budget -= 1;
      const target = cells[pick(cells.length)];
      if (target !== undefined && target.status !== ConstructionStatus.Disposed) {
        target.b = pick(4);
        target.ping();
      }
    }
    if (disposeBudget > 0 && m instanceof PropertyChangedMessage && m.propertyName === "c1") {
      disposeBudget -= 1;
      const target = cells[1 + pick(cells.length - 1)];
      if (target !== undefined && target.status !== ConstructionStatus.Disposed) target.dispose();
    }
  });
  for (let step = 0; step < steps; step += 1) {
    const before = new Map();
    for (const cell of cells) {
      if (cell.status === ConstructionStatus.Disposed) continue;
      const e = expected(cell);
      for (const name of NAMES) before.set(`${cell.name}.${name}`, e[name]);
    }
    announced.clear();
    budget = pick(3);
    disposeBudget = random() < 0.01 ? 1 : 0;
    const cell = cells[pick(cells.length)];
    if (cell.status === ConstructionStatus.Disposed) continue;
    const roll = random();
    if (roll < 0.45) {
      if (random() < 0.5) cell.a = pick(5);
      else cell.b = pick(5);
    } else if (roll < 0.65) {
      cell.change(() => {
        cell.a = pick(5);
        const other = cells[pick(cells.length)];
        if (other.status !== ConstructionStatus.Disposed) other.b = pick(5);
        cell.b = pick(5);
      });
    } else if (roll < 0.8) {
      if (cell.status === ConstructionStatus.Constructed) cell.destruct();
      else cell.construct();
    } else if (roll < 0.9) {
      if (cell.status === ConstructionStatus.Constructed) cell.reconstruct();
      else cell.construct();
    } else {
      cell.ping();
    }
    for (const target of cells) {
      if (target.status === ConstructionStatus.Disposed) continue;
      const e = expected(target);
      for (const name of NAMES) {
        const key = `${target.name}.${name}`;
        assert.equal(target[name], e[name], `seed ${seed} step ${step}: ${key} is stale`);
        if (before.has(key) && before.get(key) !== e[name]) {
          assert.ok(announced.has(key), `seed ${seed} step ${step}: ${key} changed but was not announced`);
        }
      }
      if (target.status === ConstructionStatus.Constructed) {
        assert.equal(target.lastSeen, e.c4, `seed ${seed} step ${step}: ${target.name}'s effect missed c4`);
        assert.equal(target.mirror, e.c4 % 7, `seed ${seed} step ${step}: ${target.name}.mirror`);
      }
    }
  }
}

const seeds = Number(process.argv[2] ?? 300);
const steps = Number(process.argv[3] ?? 600);
const started = performance.now();
for (let seed = 1; seed <= seeds; seed += 1) run(seed * 7919, steps);
await new Promise((resolve) => setTimeout(resolve, 20));
assert.deepEqual(unhandled, []);
console.log(`ok: ${seeds} seeds x ${steps} operations in ${(performance.now() - started).toFixed(0)} ms`);
