# 14. Performance Methodology

VMx keeps a small benchmark suite for the TypeScript, Python, and Rust flavors
under `benchmarks/`, committed baselines under `benchmarks/baselines/`, and a
comparison tool at `tools/compare-benchmarks.py`. The suite gives each change a
review signal: a person compares a run against the baseline and looks at any
case outside its noise band. It is not a CI gate, it promises no absolute speed,
and it does not rank languages. The flavors run different runtimes and
harnesses, so only runs of the same flavor on the same machine are compared.

Nothing in `benchmarks/` ships in a published package, and the harnesses use
no benchmark libraries: each one uses its runtime's own timer and allocator
statistics.

## 14.1. Run The Suite

Run each harness from the repository root on a clean checkout. A report records
whether the working tree was dirty.

```bash
# TypeScript: build the core first; --expose-gc enables the memory probe.
npm --prefix langs/typescript ci
npm --prefix langs/typescript run build
node --expose-gc benchmarks/typescript/run.mjs --out ts.json

# Python
uv run --project langs/python python benchmarks/python/run.py --out py.json

# Rust
cargo run --release --locked --manifest-path benchmarks/rust/Cargo.toml -- --out rust.json
```

All three harnesses accept the same options:

| Option          | Effect                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| `--out PATH`    | Write the JSON report to `PATH`; without it the report goes to stdout. |
| `--rounds N`    | Measured rounds per case; default 9.                                   |
| `--warmup N`    | Discarded warm-up rounds per case; default 2.                          |
| `--seed N`      | Seed for generated workload values; default 1.                         |
| `--only PREFIX` | Run only the cases whose id starts with `PREFIX`; skips the probe.     |
| `--quick`       | Smoke run: 5% of the operations, 1 warm-up and 3 measured rounds.      |

A full run takes two to four minutes per flavor. Quick runs are for checking
that a harness works; never compare one with a baseline.

## 14.2. Method

- **Warm-up.** Each case runs two discarded rounds before nine measured ones,
  so JIT compilation, interpreter caches, and allocator pools settle first.
- **Iteration.** A case performs a fixed number of operations per round, set
  in its parameters, and its sample is the round's elapsed time divided by that
  count, in nanoseconds per operation. The report keeps every sample along with
  the median, the median absolute deviation (MAD), and `rel_mad`, the MAD divided
  by the median.
- **Order.** Round *r* starts at case *r* mod *n* and continues through the list,
  so no case always runs first or last and drift spreads across all cases.
- **Source lifetime.** Before each round a case builds its sources outside the
  timed region: a fresh hub, its subscribers, and any view-model or observer it
  measures. The timed region contains only the operations. Collection cases
  create each list inside the timed region, because creating and filling a list
  is the workload.
- **Cleanup.** After each round the case unsubscribes, disposes its
  view-models, observers, and hub outside the timed region. TypeScript (with
  `--expose-gc`) and Python collect garbage before each round; Rust frees
  memory deterministically.
- **Seeds.** `property.set` assigns values from a seeded generator, so every
  run assigns the same sequence and every assignment changes the model.

## 14.3. Cases

Case ids are the same in every flavor where the workload exists, so a reader can
line up the same workload across reports without comparing their numbers.

| Case                                 | Workload                                                                       |
| ------------------------------------ | ------------------------------------------------------------------------------ |
| `hub.send/subscribers=0`, `1`, `100` | Send one property-change message to a hub with no, one, or 100 subscribers.    |
| `hub.observer/plain`                 | The same send with nothing observing the hub.                                  |
| `hub.observer/disconnected` (TS)     | `connectReduxDevtools(hub, { extension: null })` attached: disabled observing. |
| `hub.observer/active` (TS, Python)   | An observer that reads each message: `observeHub` in TypeScript.               |
| `hub.observer/recorder` (Rust)       | A `MessageRecorder` of capacity 1,024 attached (ADR-0141).                     |
| `hub.batch/size=100`, `1000`         | Bursts of 100 or 1,000 sends inside one `batch` transaction, one subscriber.   |
| `property.set`                       | Assign a new model to a component view-model whose hub has one subscriber.     |
| `collection.push/size=…`             | Fill an observable list to 1,000, 10,000, or 100,000 items by appending.       |
| `collection.insert0/size=…`          | Fill a list to 1,000 or 10,000 items by inserting at the front.                |
| `lifecycle.construct_dispose`        | Build, construct, and dispose a component view-model on a shared hub.          |

The cases cover disabled observer overhead (`disconnected` against `plain`),
large subscriber counts (`subscribers=100`), transaction bursts (`hub.batch`),
and collection sizes that expose growth. If an operation's cost rises with the
list's size, `collection.push` or `collection.insert0` shows it as a rising cost
per operation across sizes.

The TypeScript `hub.observer` cases reproduce the DevTools pilot
([2026-08-11 pilot](../maintenance/2026-08-11-typescript-devtools-daydreams-pilot.md)):
150,000 messages, two warm-up rounds, rotated order, and the median of nine
rounds.

## 14.4. Memory And Queue Probe

Every full run also runs the `lifecycle.memory` probe. It builds, constructs,
and disposes a component view-model over six batches on one hub with one
subscriber: 20,000 cycles per batch in TypeScript and Rust, 5,000 in Python.
After each batch it sends one message and records how many sent messages were
still undelivered (the queue depth). It then measures retained memory: V8
`heapUsed` after a forced collection in TypeScript, `tracemalloc` traced bytes
in Python, and live bytes from a counting global allocator in Rust. The first
batch is warm-up, so growth runs from the end of the first batch to the end of
the last.

The probe reports `bounded: true` only when growth stays under its limit
(4 MiB in TypeScript, 2 MiB in Python, 1 MiB in Rust) and the queue depth stays
zero. It also records the hub's event-history size, because a hub that keeps
delivered messages would hide a leak inside "expected" retention. TypeScript and
Python hubs keep no history. Rust reports `MessageHub::history().len()`, and
from version 0.31.0 a Rust hub retains nothing either (ADR-0141), so the probe
also requires that size to be zero. A harness exits 1 when its probe is not
bounded. Measured on the Rust crate from before ADR-0141, the same probe
reports growth of 1,648,354 bytes and a history of 15,005 messages, and fails.

## 14.5. Report Format

Every harness writes a `vmx-bench/1` JSON report:

| Field             | Contents                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------- |
| `flavor`          | `typescript`, `python`, or `rust`.                                                          |
| `commit`, `dirty` | `git rev-parse HEAD` and whether `git status --porcelain` was non-empty.                    |
| `package_version` | The flavor's package version from its manifest.                                             |
| `runtime`         | Runtime name and version: Node and V8, CPython and implementation, or rustc.                |
| `hardware`        | CPU model, logical cores, architecture, and platform; Node and Python add the OS release.   |
| `workload`        | Seed, warm-up and measured rounds, order, `quick`, garbage collection, and any slowdown.    |
| `cases`           | Per case: id, unit, parameters, operation count, median, MAD, `rel_mad`, min, max, samples. |
| `probes`          | The `lifecycle.memory` result described above.                                              |

## 14.6. Review Thresholds

`tools/compare-benchmarks.py BASELINE CANDIDATE` compares two reports case by
case. Each case's band comes from the variance the two runs measured:

```text
band = max(5%, 4 × max(baseline rel_mad, candidate rel_mad))
```

The tool marks a case `SLOWER` when the candidate's median exceeds the
baseline's by more than the band, and `FASTER` when it is lower by the same
margin. It also lists cases only one report has. It exits 1 when any case is
slower or the candidate's probe is not bounded. It warns when the reports differ
in flavor, CPU, core count, architecture, runtime version, or `--quick`;
`--strict` turns that warning into exit 2. The multiplier and floor can be
changed with `--k` and `--floor`.

Because MAD tracks the median rather than the extremes, one slow round does not
widen the band. Four MADs is wide enough that two consecutive runs on the
recording machine flagged no case, and narrow enough that an injected slowdown
was flagged in every flavor:

RESULTS_TABLE

To show detection, set `VMX_BENCH_SLOWDOWN="case-id=iterations"`. Each
operation of the named case then adds a fixed spin loop, and the report records
the setting. A harness rejects an id that names no case. Committed baselines
never carry a slowdown.

## 14.7. Baselines

`benchmarks/baselines/` holds one report per flavor, recorded on a clean
checkout of the commit named in the report. Compare a change against the
baseline of its flavor:

```bash
node --expose-gc benchmarks/typescript/run.mjs --out ts.json
python3 tools/compare-benchmarks.py benchmarks/baselines/2026-10-07-typescript.json ts.json
```

A run on another machine is not like for like: the tool warns, and its result
says how this change compares on that machine only. To review a change on your
own machine, record a baseline from the base branch first, then compare the
change against it. To replace a committed baseline, record a full run on a
clean checkout, name the file by date and flavor, and explain in the pull
request why the old one no longer represents the code.

## 14.8. Limits

- The committed baselines come from a shared cloud container, not a quiet
  dedicated machine, so their bands are wider than a dedicated machine's would
  be. The method is the same on any machine; only the numbers change.
- C# and Swift have no harness yet. Their runtimes need their own tooling
  (BenchmarkDotNet-style harnesses for .NET, XCTest `measure` blocks or a
  release-mode executable for Swift) and would be compared only with
  themselves.
- The numbers describe the recording machine and these workloads. Applications
  should measure their own message shapes, subscribers, and observers.
