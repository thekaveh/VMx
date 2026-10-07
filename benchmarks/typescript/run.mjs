#!/usr/bin/env node
// VMx TypeScript benchmark harness. Method and report format:
// docs/content/performance-methodology.md. Run after building the core:
//   npm --prefix langs/typescript run build
//   node --expose-gc benchmarks/typescript/run.mjs --out report.json
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const DIST = path.join(ROOT, "langs/typescript/dist");
const core = await import(pathToFileURL(path.join(DIST, "index.js")).href);
const devtools = await import(pathToFileURL(path.join(DIST, "devtools.js")).href);
const { ComponentVMOf, MessageHub, NullDispatcher, ObservableList, PropertyChangedMessage } = core;

function parseArgs(argv) {
  const options = { out: null, rounds: 9, warmup: 2, quick: false, seed: 1, only: null };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = () => argv[++index];
    if (flag === "--out") options.out = value();
    else if (flag === "--rounds") options.rounds = Number(value());
    else if (flag === "--warmup") options.warmup = Number(value());
    else if (flag === "--seed") options.seed = Number(value());
    else if (flag === "--only") options.only = value();
    else if (flag === "--quick") options.quick = true;
    else throw new Error(`unknown argument ${flag}`);
  }
  if (options.quick) Object.assign(options, { rounds: 3, warmup: 1 });
  return options;
}

const options = parseArgs(process.argv.slice(2));
const scale = options.quick ? 0.05 : 1;
const size = (count) => Math.max(1, Math.round(count * scale));

// VMX_BENCH_SLOWDOWN="case-id=iterations" adds a fixed spin per operation to
// one case, to show that the comparison flags a known regression.
const slowdown = new Map(
  (process.env.VMX_BENCH_SLOWDOWN ?? "")
    .split(",")
    .filter(Boolean)
    .map((entry) => {
      const [id, iterations] = entry.split("=");
      return [id, Number(iterations)];
    }),
);
let sink = 0;
function spinner(id) {
  const iterations = slowdown.get(id) ?? 0;
  if (iterations === 0) return () => {};
  return () => {
    for (let index = 0; index < iterations; index += 1) sink = (sink + index) % 1_000_003;
  };
}

function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state;
  };
}

const sender = { name: "bench" };
const message = PropertyChangedMessage.create(sender, "bench", "value");

function subscribe(hub, count, onNext = () => {}) {
  return Array.from({ length: count }, () => hub.messages.subscribe({ next: onNext }));
}

function sendCase(subscribers, messages) {
  const id = `hub.send/subscribers=${subscribers}`;
  return {
    id,
    params: { subscribers, messages },
    ops: messages,
    setup() {
      const hub = new MessageHub();
      return { hub, subscriptions: subscribe(hub, subscribers), spin: spinner(id) };
    },
    run({ hub, spin }) {
      for (let index = 0; index < messages; index += 1) {
        hub.send(message);
        spin();
      }
    },
    teardown({ hub, subscriptions }) {
      subscriptions.forEach((subscription) => subscription.unsubscribe());
      hub.dispose();
    },
  };
}

function observerCase(mode, messages) {
  const id = `hub.observer/${mode}`;
  return {
    id,
    params: { mode, messages },
    ops: messages,
    setup() {
      const hub = new MessageHub();
      let connection = null;
      if (mode === "disconnected") connection = devtools.connectReduxDevtools(hub, { extension: null });
      if (mode === "active") connection = devtools.observeHub(hub, () => {});
      return { hub, connection, spin: spinner(id) };
    },
    run({ hub, spin }) {
      for (let index = 0; index < messages; index += 1) {
        hub.send(message);
        spin();
      }
    },
    teardown({ hub, connection }) {
      connection?.dispose();
      hub.dispose();
    },
  };
}

function batchCase(batchSize, messages) {
  const id = `hub.batch/size=${batchSize}`;
  const batches = Math.max(1, Math.round(messages / batchSize));
  return {
    id,
    params: { batch_size: batchSize, batches, subscribers: 1 },
    ops: batches * batchSize,
    setup() {
      const hub = new MessageHub();
      return { hub, subscriptions: subscribe(hub, 1), spin: spinner(id) };
    },
    run({ hub, spin }) {
      for (let batch = 0; batch < batches; batch += 1) {
        hub.batch(() => {
          for (let index = 0; index < batchSize; index += 1) {
            hub.send(message);
            spin();
          }
        });
      }
    },
    teardown({ hub, subscriptions }) {
      subscriptions.forEach((subscription) => subscription.unsubscribe());
      hub.dispose();
    },
  };
}

function propertyCase(assignments, seed) {
  const id = "property.set";
  return {
    id,
    params: { assignments, subscribers: 1 },
    ops: assignments,
    setup() {
      const hub = new MessageHub();
      const vm = ComponentVMOf.create({
        name: "bench",
        hub,
        dispatcher: NullDispatcher.INSTANCE,
        model: 0,
      });
      const next = lcg(seed);
      const values = Array.from({ length: assignments }, (_, index) => index * 2 + (next() % 2) + 1);
      return { hub, vm, values, subscriptions: subscribe(hub, 1), spin: spinner(id) };
    },
    run({ vm, values, spin }) {
      for (const value of values) {
        vm.model = value;
        spin();
      }
    },
    teardown({ hub, vm, subscriptions }) {
      subscriptions.forEach((subscription) => subscription.unsubscribe());
      vm.dispose();
      hub.dispose();
    },
  };
}

function collectionCase(operation, length, totalOps) {
  const id = `collection.${operation}/size=${length}`;
  const repetitions = Math.max(1, Math.round(totalOps / length));
  return {
    id,
    params: { operation, size: length, repetitions },
    ops: repetitions * length,
    setup() {
      return { spin: spinner(id) };
    },
    run({ spin }) {
      for (let repetition = 0; repetition < repetitions; repetition += 1) {
        const list = new ObservableList();
        for (let index = 0; index < length; index += 1) {
          if (operation === "push") list.push(index);
          else list.insert(0, index);
          spin();
        }
      }
    },
    teardown() {},
  };
}

function lifecycleCase(cycles) {
  const id = "lifecycle.construct_dispose";
  return {
    id,
    params: { cycles },
    ops: cycles,
    setup() {
      const hub = new MessageHub();
      return { hub, subscriptions: subscribe(hub, 1), spin: spinner(id) };
    },
    run({ hub, spin }) {
      for (let cycle = 0; cycle < cycles; cycle += 1) {
        const vm = ComponentVMOf.create({
          name: "cycle",
          hub,
          dispatcher: NullDispatcher.INSTANCE,
          model: cycle,
        });
        vm.construct();
        vm.dispose();
        spin();
      }
    },
    teardown({ hub, subscriptions }) {
      subscriptions.forEach((subscription) => subscription.unsubscribe());
      hub.dispose();
    },
  };
}

const cases = [
  sendCase(0, size(150_000)),
  sendCase(1, size(150_000)),
  sendCase(100, size(15_000)),
  observerCase("plain", size(150_000)),
  observerCase("disconnected", size(150_000)),
  observerCase("active", size(150_000)),
  batchCase(100, size(100_000)),
  batchCase(1000, size(100_000)),
  propertyCase(size(100_000), options.seed),
  collectionCase("push", 1_000, size(100_000)),
  collectionCase("push", 10_000, size(100_000)),
  collectionCase("push", 100_000, size(100_000)),
  collectionCase("insert0", 1_000, size(20_000)),
  collectionCase("insert0", 10_000, size(20_000)),
  lifecycleCase(size(20_000)),
].filter((entry) => options.only === null || entry.id.startsWith(options.only));

function collectGarbage() {
  if (typeof globalThis.gc === "function") globalThis.gc();
}

function measure(entry) {
  const state = entry.setup();
  collectGarbage();
  const start = performance.now();
  entry.run(state);
  const elapsed = performance.now() - start;
  entry.teardown(state);
  return (elapsed * 1e6) / entry.ops;
}

function stats(samples) {
  const sorted = [...samples].sort((left, right) => left - right);
  const middle = (values) => {
    const half = Math.floor(values.length / 2);
    return values.length % 2 ? values[half] : (values[half - 1] + values[half]) / 2;
  };
  const median = middle(sorted);
  const mad = middle(sorted.map((value) => Math.abs(value - median)).sort((left, right) => left - right));
  return {
    median,
    mad,
    rel_mad: median === 0 ? 0 : mad / median,
    min: sorted[0],
    max: sorted[sorted.length - 1],
  };
}

const samples = new Map(cases.map((entry) => [entry.id, []]));
for (let round = 0; round < options.warmup + options.rounds; round += 1) {
  for (let offset = 0; offset < cases.length; offset += 1) {
    const entry = cases[(round + offset) % cases.length];
    const value = measure(entry);
    if (round >= options.warmup) samples.get(entry.id).push(value);
  }
}

// Bounded memory and queue depth over repeated construct/dispose cycles.
function lifecycleMemoryProbe(batches, cyclesPerBatch) {
  if (typeof globalThis.gc !== "function") {
    return { skipped: "run node with --expose-gc to measure retained memory" };
  }
  const hub = new MessageHub();
  let delivered = 0;
  const subscription = hub.messages.subscribe({ next: () => { delivered += 1; } });
  const heap = [];
  let maxQueueDepth = 0;
  collectGarbage();
  heap.push(process.memoryUsage().heapUsed);
  for (let batch = 0; batch < batches; batch += 1) {
    for (let cycle = 0; cycle < cyclesPerBatch; cycle += 1) {
      const vm = ComponentVMOf.create({ name: "probe", hub, dispatcher: NullDispatcher.INSTANCE, model: cycle });
      vm.construct();
      vm.dispose();
    }
    const before = delivered;
    hub.send(message);
    maxQueueDepth = Math.max(maxQueueDepth, 1 - (delivered - before));
    collectGarbage();
    heap.push(process.memoryUsage().heapUsed);
  }
  subscription.unsubscribe();
  hub.dispose();
  // The first batch is warm-up (JIT and runtime caches); growth is measured
  // across the remaining batches, where a per-cycle leak would accumulate.
  const growth = heap[heap.length - 1] - heap[1];
  const limit = 4 * 1024 * 1024;
  return {
    cycles: batches * cyclesPerBatch,
    warmup_batches: 1,
    retained_bytes_samples: heap,
    retained_growth_bytes: growth,
    retained_growth_limit_bytes: limit,
    bounded: growth < limit && maxQueueDepth === 0,
    max_queue_depth: maxQueueDepth,
    hub_history_size: 0,
    hub_history_note: "TypeScript hubs retain no delivered messages",
  };
}

function git(...args) {
  try {
    return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
  } catch {
    return null;
  }
}

const cpus = os.cpus();
const report = {
  schema: "vmx-bench/1",
  flavor: "typescript",
  timestamp: new Date().toISOString(),
  commit: git("rev-parse", "HEAD"),
  dirty: (git("status", "--porcelain") ?? "") !== "",
  package_version: JSON.parse(readFileSync(path.join(ROOT, "langs/typescript/package.json"), "utf8")).version,
  runtime: { name: "node", version: process.version, v8: process.versions.v8 },
  hardware: {
    cpu_model: cpus[0]?.model ?? "unknown",
    logical_cores: cpus.length,
    arch: os.arch(),
    platform: os.platform(),
    os_release: os.release(),
    total_memory_bytes: os.totalmem(),
  },
  workload: {
    seed: options.seed,
    warmup_rounds: options.warmup,
    measured_rounds: options.rounds,
    order: "rotated: round r starts at case r mod n",
    quick: options.quick,
    gc_between_cases: typeof globalThis.gc === "function",
    slowdown: Object.fromEntries(slowdown),
  },
  cases: cases.map((entry) => ({
    id: entry.id,
    unit: "ns/op",
    params: entry.params,
    ops: entry.ops,
    ...stats(samples.get(entry.id)),
    samples: samples.get(entry.id),
  })),
  probes: {
    "lifecycle.memory": options.only === null
      ? lifecycleMemoryProbe(6, options.quick ? 1_000 : 20_000)
      : { skipped: "--only" },
  },
};

const text = `${JSON.stringify(report, null, 2)}\n`;
if (options.out) writeFileSync(options.out, text);
else process.stdout.write(text);
for (const entry of report.cases) {
  process.stderr.write(
    `${entry.id.padEnd(36)} ${entry.median.toFixed(1).padStart(10)} ns/op  ±${(entry.rel_mad * 100).toFixed(1)}%\n`,
  );
}
const probe = report.probes["lifecycle.memory"];
if (probe.bounded === false) {
  process.stderr.write("lifecycle.memory probe exceeded its bound\n");
  process.exitCode = 1;
}
if (sink < 0) process.stderr.write("");
