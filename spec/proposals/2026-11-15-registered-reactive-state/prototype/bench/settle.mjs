// Micro-benchmark (informative): activation and settle costs for 70 view-models.
import { ComponentVM, MessageHub, RxDispatcher } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics } from "../build/src/index.js";

configureReactiveDiagnostics({ development: false });
const hub = new MessageHub({ developmentDiagnostics: false });
const dispatcher = RxDispatcher.immediate();
const base = (name) => ({ name, hint: "", hub, dispatcher });

class Settings extends ComponentVM {
  constructor() { super(base("settings")); this.observable({ theme: "light", unit: "s" }); }
}
const settings = new Settings();

class Item extends ComponentVM {
  constructor(i) {
    super(base(`item${i}`));
    this.set = this.observable({ value: i, empty: false, open: false });
    this.computed("t1", "t2", "t3", "t4", "t5", "o1", "o2", "o3", "o4", "o5");
  }
  get t1() { return `${settings.theme}-1`; }
  get t2() { return `${this.t1}:${settings.unit}`; }
  get t3() { return settings.theme === "dark"; }
  get t4() { return this.t3 ? "on" : "off"; }
  get t5() { return [this.t2, this.t4].join("/"); }
  get o1() { return this.value * 2; }
  get o2() { return this.o1 + 1; }
  get o3() { return this.empty && !this.open; }
  get o4() { return this.o3 ? "Show" : "Hide"; }
  get o5() { return `${this.o2}${this.o4}`; }
}

function time(label, runs, fn) {
  fn();
  const start = process.hrtime.bigint();
  for (let i = 0; i < runs; i += 1) fn(i);
  const us = Number(process.hrtime.bigint() - start) / 1000 / runs;
  console.log(`${label}: ${us.toFixed(1)} us`);
}

const items = [];
let t0 = process.hrtime.bigint();
for (let i = 0; i < 70; i += 1) items.push(new Item(i));
const createUs = Number(process.hrtime.bigint() - t0) / 1000;
t0 = process.hrtime.bigint();
for (const item of items) activate(item);
const activateUs = Number(process.hrtime.bigint() - t0) / 1000;
console.log(`create 70 view-models (700 computeds registered): ${createUs.toFixed(0)} us`);
console.log(`activate 70 view-models (700 baselines): ${activateUs.toFixed(0)} us`);

let flip = false;
time("theme write -> 350 computeds re-evaluated, 350 announced (no subscribers)", 200, () => {
  flip = !flip;
  settings.set ??= null;
  settings.theme = flip ? "dark" : "light";
});
let n = 1000;
time("one view-model state write -> 2 computeds, 3 announcements", 2000, () => {
  n += 1;
  items[3].value = n;
});
let count = 0;
hub.messages.subscribe(() => { count += 1; });
for (const item of items) item.propertyChanged.subscribe(() => { count += 1; });
time("theme write with 1 hub subscriber + 70 local subscribers", 200, () => {
  flip = !flip;
  settings.theme = flip ? "dark" : "light";
});
time("unit write (t2, t5 change)", 200, (i) => {
  settings.unit = `u${i ?? 0}`;
});
console.log(`deliveries counted: ${count}`);
