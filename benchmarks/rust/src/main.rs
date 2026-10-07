//! VMx Rust benchmark harness.
//!
//! Method and report format: `docs/content/performance-methodology.md`. Run
//! from the repository root:
//!
//! ```text
//! cargo run --release --locked --manifest-path benchmarks/rust/Cargo.toml -- --out report.json
//! ```

use std::alloc::{GlobalAlloc, Layout, System};
use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::process::Command;
use std::sync::atomic::{AtomicIsize, AtomicU64, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use vmx::{
    ComponentVm, Message, MessageHub, NullDispatcher, ObservableList, PropertyChangedMessage,
};

/// Counts live heap bytes so the lifecycle probe can measure retained memory
/// without an external allocator crate.
struct CountingAllocator;

static LIVE_BYTES: AtomicIsize = AtomicIsize::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            LIVE_BYTES.fetch_add(layout.size() as isize, Ordering::Relaxed);
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        unsafe { System.dealloc(pointer, layout) };
        LIVE_BYTES.fetch_sub(layout.size() as isize, Ordering::Relaxed);
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

struct Options {
    out: Option<String>,
    rounds: usize,
    warmup: usize,
    seed: u64,
    only: Option<String>,
    quick: bool,
}

fn parse_options() -> Options {
    let mut options = Options {
        out: None,
        rounds: 9,
        warmup: 2,
        seed: 1,
        only: None,
        quick: false,
    };
    let mut arguments = std::env::args().skip(1);
    while let Some(flag) = arguments.next() {
        let mut value = || arguments.next().expect("missing flag value");
        match flag.as_str() {
            "--out" => options.out = Some(value()),
            "--rounds" => options.rounds = value().parse().expect("--rounds"),
            "--warmup" => options.warmup = value().parse().expect("--warmup"),
            "--seed" => options.seed = value().parse().expect("--seed"),
            "--only" => options.only = Some(value()),
            "--quick" => options.quick = true,
            other => panic!("unknown argument {other}"),
        }
    }
    if options.quick {
        options.rounds = 3;
        options.warmup = 1;
    }
    options
}

/// `VMX_BENCH_SLOWDOWN="case-id=iterations"` adds a fixed spin per operation
/// to one case, to show that the comparison flags a known regression. Case
/// ids contain `=` themselves, so the count follows the last one.
fn slowdown() -> BTreeMap<String, u64> {
    std::env::var("VMX_BENCH_SLOWDOWN")
        .unwrap_or_default()
        .split(',')
        .filter(|entry| !entry.is_empty())
        .map(|entry| {
            let parsed = entry
                .rsplit_once('=')
                .filter(|(id, _)| !id.is_empty())
                .and_then(|(id, iterations)| Some((id.to_string(), iterations.parse().ok()?)));
            parsed.unwrap_or_else(|| {
                panic!("VMX_BENCH_SLOWDOWN entry {entry:?} is not case-id=iterations")
            })
        })
        .collect()
}

static SINK: AtomicU64 = AtomicU64::new(0);

fn spin(iterations: u64) {
    let mut total = 0u64;
    for index in 0..iterations {
        total = std::hint::black_box((total + index) % 1_000_003);
    }
    SINK.fetch_add(total, Ordering::Relaxed);
}

struct Case {
    id: String,
    params: Vec<(&'static str, String)>,
    ops: u64,
    run: Box<dyn Fn(u64)>,
    samples: Vec<f64>,
}

fn message() -> Message {
    Message::PropertyChanged(PropertyChangedMessage {
        sender_id: 1,
        sender_name: "bench".into(),
        property_name: "value".into(),
    })
}

fn send_case(subscribers: usize, messages: u64) -> Case {
    Case {
        id: format!("hub.send/subscribers={subscribers}"),
        params: vec![
            ("subscribers", subscribers.to_string()),
            ("messages", messages.to_string()),
        ],
        ops: messages,
        run: Box::new(move |spin_iterations| {
            let hub = MessageHub::new();
            let _subscriptions: Vec<_> = (0..subscribers).map(|_| hub.subscribe(|_| {})).collect();
            let message = message();
            for _ in 0..messages {
                hub.send(message.clone());
                spin(spin_iterations);
            }
            hub.dispose();
        }),
        samples: Vec::new(),
    }
}

fn observer_case(mode: &'static str, messages: u64) -> Case {
    Case {
        id: format!("hub.observer/{mode}"),
        params: vec![
            ("mode", mode.to_string()),
            ("messages", messages.to_string()),
        ],
        ops: messages,
        run: Box::new(move |spin_iterations| {
            let hub = MessageHub::new();
            let recorder = (mode == "recorder").then(|| hub.record(1024));
            let message = message();
            for _ in 0..messages {
                hub.send(message.clone());
                spin(spin_iterations);
            }
            drop(recorder);
            hub.dispose();
        }),
        samples: Vec::new(),
    }
}

fn batch_case(batch_size: u64, messages: u64) -> Case {
    let batches = (messages / batch_size).max(1);
    Case {
        id: format!("hub.batch/size={batch_size}"),
        params: vec![
            ("batch_size", batch_size.to_string()),
            ("batches", batches.to_string()),
            ("subscribers", "1".into()),
        ],
        ops: batches * batch_size,
        run: Box::new(move |spin_iterations| {
            let hub = MessageHub::new();
            let _subscription = hub.subscribe(|_| {});
            let message = message();
            for _ in 0..batches {
                hub.batch(|| {
                    for _ in 0..batch_size {
                        hub.send(message.clone());
                        spin(spin_iterations);
                    }
                });
            }
            hub.dispose();
        }),
        samples: Vec::new(),
    }
}

fn property_case(assignments: u64, seed: u64) -> Case {
    Case {
        id: "property.set".into(),
        params: vec![
            ("assignments", assignments.to_string()),
            ("subscribers", "1".into()),
        ],
        ops: assignments,
        run: Box::new(move |spin_iterations| {
            let hub = MessageHub::new();
            let _subscription = hub.subscribe(|_| {});
            let vm = ComponentVm::with_model("bench", 0u64, hub.clone(), NullDispatcher::new());
            let mut state = seed;
            for index in 0..assignments {
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                vm.set_model(index * 2 + (state >> 63) + 1);
                spin(spin_iterations);
            }
            let _ = vm.dispose();
            hub.dispose();
        }),
        samples: Vec::new(),
    }
}

fn collection_case(operation: &'static str, length: u64, total_ops: u64) -> Case {
    let repetitions = (total_ops / length).max(1);
    Case {
        id: format!("collection.{operation}/size={length}"),
        params: vec![
            ("operation", operation.to_string()),
            ("size", length.to_string()),
            ("repetitions", repetitions.to_string()),
        ],
        ops: repetitions * length,
        run: Box::new(move |spin_iterations| {
            for _ in 0..repetitions {
                let hub = MessageHub::new();
                let list = ObservableList::new(1, hub.clone());
                for index in 0..length {
                    if operation == "push" {
                        list.push(index);
                    } else {
                        list.insert(0, index).expect("insert at front");
                    }
                    spin(spin_iterations);
                }
                hub.dispose();
            }
        }),
        samples: Vec::new(),
    }
}

fn lifecycle_case(cycles: u64) -> Case {
    Case {
        id: "lifecycle.construct_dispose".into(),
        params: vec![("cycles", cycles.to_string())],
        ops: cycles,
        run: Box::new(move |spin_iterations| {
            let hub = MessageHub::new();
            let _subscription = hub.subscribe(|_| {});
            for cycle in 0..cycles {
                let vm =
                    ComponentVm::with_model("cycle", cycle, hub.clone(), NullDispatcher::new());
                vm.construct().expect("construct");
                vm.dispose().expect("dispose");
                spin(spin_iterations);
            }
            hub.dispose();
        }),
        samples: Vec::new(),
    }
}

fn median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let half = sorted.len() / 2;
    if sorted.len() % 2 == 1 {
        sorted[half]
    } else {
        (sorted[half - 1] + sorted[half]) / 2.0
    }
}

/// Bounded memory and queue depth over repeated construct/dispose cycles.
fn lifecycle_memory_probe(batches: u64, cycles_per_batch: u64) -> String {
    let hub = MessageHub::new();
    let delivered = std::sync::Arc::new(AtomicU64::new(0));
    let counter = delivered.clone();
    let subscription = hub.subscribe(move |_| {
        counter.fetch_add(1, Ordering::Relaxed);
    });
    let mut retained = vec![LIVE_BYTES.load(Ordering::Relaxed)];
    let mut max_queue_depth = 0u64;
    for _ in 0..batches {
        for cycle in 0..cycles_per_batch {
            let vm = ComponentVm::with_model("probe", cycle, hub.clone(), NullDispatcher::new());
            vm.construct().expect("construct");
            vm.dispose().expect("dispose");
        }
        let before = delivered.load(Ordering::Relaxed);
        hub.send(message());
        max_queue_depth = max_queue_depth.max(1 - (delivered.load(Ordering::Relaxed) - before));
        retained.push(LIVE_BYTES.load(Ordering::Relaxed));
    }
    #[allow(deprecated)]
    let history_size = hub.history().len();
    drop(subscription);
    hub.dispose();
    // The first batch is warm-up; growth is measured across the remaining
    // batches, where a per-cycle leak would accumulate.
    let growth = retained.last().unwrap() - retained[1];
    let limit: isize = 1024 * 1024;
    let bounded = growth < limit && max_queue_depth == 0 && history_size == 0;
    let samples = retained
        .iter()
        .map(ToString::to_string)
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{{\n      \"cycles\": {cycles},\n      \"warmup_batches\": 1,\n      \"retained_bytes_samples\": [{samples}],\n      \
         \"retained_growth_bytes\": {growth},\n      \"retained_growth_limit_bytes\": {limit},\n      \
         \"bounded\": {bounded},\n      \"max_queue_depth\": {max_queue_depth},\n      \
         \"hub_history_size\": {history_size},\n      \
         \"hub_history_note\": \"MessageHub::history() length after the cycles (ADR-0141: hubs retain nothing)\"\n    }}",
        cycles = batches * cycles_per_batch,
    )
}

fn json_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for character in value.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            control if control.is_control() => {
                let _ = write!(escaped, "\\u{:04x}", control as u32);
            }
            other => escaped.push(other),
        }
    }
    escaped.push('"');
    escaped
}

fn git(arguments: &[&str]) -> Option<String> {
    let output = Command::new("git").args(arguments).output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn cpu_model() -> String {
    std::fs::read_to_string("/proc/cpuinfo")
        .ok()
        .and_then(|text| {
            text.lines()
                .find(|line| line.starts_with("model name"))
                .and_then(|line| line.split_once(':'))
                .map(|(_, model)| model.trim().to_string())
        })
        .unwrap_or_else(|| "unknown".into())
}

fn rustc_version() -> String {
    Command::new("rustc")
        .arg("--version")
        .output()
        .ok()
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_string())
        .unwrap_or_else(|| "unknown".into())
}

fn main() {
    let options = parse_options();
    let scale = if options.quick { 0.05 } else { 1.0 };
    let size = |count: u64| ((count as f64 * scale).round() as u64).max(1);
    let slowdown = slowdown();
    let mut cases = vec![
        send_case(0, size(150_000)),
        send_case(1, size(150_000)),
        send_case(100, size(15_000)),
        observer_case("plain", size(150_000)),
        observer_case("recorder", size(150_000)),
        batch_case(100, size(100_000)),
        batch_case(1000, size(100_000)),
        property_case(size(100_000), options.seed),
        collection_case("push", 1_000, size(100_000)),
        collection_case("push", 10_000, size(100_000)),
        collection_case("push", 100_000, size(100_000)),
        collection_case("insert0", 1_000, size(20_000)),
        collection_case("insert0", 10_000, size(20_000)),
        lifecycle_case(size(20_000)),
    ];
    let unknown: Vec<&str> = slowdown
        .keys()
        .filter(|id| !cases.iter().any(|case| &case.id == *id))
        .map(String::as_str)
        .collect();
    assert!(
        unknown.is_empty(),
        "VMX_BENCH_SLOWDOWN names unknown cases: {}",
        unknown.join(", ")
    );
    if let Some(prefix) = &options.only {
        cases.retain(|case| case.id.starts_with(prefix.as_str()));
    }

    let count = cases.len();
    for round in 0..options.warmup + options.rounds {
        for offset in 0..count {
            let case = &mut cases[(round + offset) % count];
            let spin_iterations = slowdown.get(&case.id).copied().unwrap_or(0);
            let start = Instant::now();
            (case.run)(spin_iterations);
            let nanos_per_op = start.elapsed().as_nanos() as f64 / case.ops as f64;
            if round >= options.warmup {
                case.samples.push(nanos_per_op);
            }
        }
    }

    let probe = if options.only.is_none() {
        lifecycle_memory_probe(6, if options.quick { 1_000 } else { 20_000 })
    } else {
        "{ \"skipped\": \"--only\" }".to_string()
    };
    let probe_bounded = !probe.contains("\"bounded\": false");

    let mut cases_json = Vec::new();
    for case in &cases {
        let mid = median(&case.samples);
        let deviations: Vec<f64> = case
            .samples
            .iter()
            .map(|value| (value - mid).abs())
            .collect();
        let mad = median(&deviations);
        let rel_mad = if mid == 0.0 { 0.0 } else { mad / mid };
        let min = case.samples.iter().copied().fold(f64::INFINITY, f64::min);
        let max = case
            .samples
            .iter()
            .copied()
            .fold(f64::NEG_INFINITY, f64::max);
        let params = case
            .params
            .iter()
            .map(|(key, value)| match value.parse::<u64>() {
                Ok(number) => format!("{}: {number}", json_string(key)),
                Err(_) => format!("{}: {}", json_string(key), json_string(value)),
            })
            .collect::<Vec<_>>()
            .join(", ");
        let samples = case
            .samples
            .iter()
            .map(|value| format!("{value:.3}"))
            .collect::<Vec<_>>()
            .join(", ");
        cases_json.push(format!(
            "    {{\n      \"id\": {id},\n      \"unit\": \"ns/op\",\n      \"params\": {{ {params} }},\n      \
             \"ops\": {ops},\n      \"median\": {mid:.3},\n      \"mad\": {mad:.3},\n      \
             \"rel_mad\": {rel_mad:.6},\n      \"min\": {min:.3},\n      \"max\": {max:.3},\n      \
             \"samples\": [{samples}]\n    }}",
            id = json_string(&case.id),
            ops = case.ops,
        ));
        eprintln!(
            "{:<36} {:>10.1} ns/op  ±{:.1}%",
            case.id,
            mid,
            rel_mad * 100.0
        );
    }

    let slowdown_json = slowdown
        .iter()
        .map(|(id, iterations)| format!("{}: {iterations}", json_string(id)))
        .collect::<Vec<_>>()
        .join(", ");
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    let dirty = git(&["status", "--porcelain"]).is_some_and(|status| !status.is_empty());
    let commit = git(&["rev-parse", "HEAD"]).map_or("null".into(), |commit| json_string(&commit));
    let report = format!(
        "{{\n  \"schema\": \"vmx-bench/1\",\n  \"flavor\": \"rust\",\n  \"timestamp\": {timestamp},\n  \
         \"commit\": {commit},\n  \"dirty\": {dirty},\n  \"package_version\": {version},\n  \
         \"runtime\": {{ \"name\": \"rustc\", \"version\": {rustc}, \"profile\": {profile} }},\n  \
         \"hardware\": {{ \"cpu_model\": {cpu}, \"logical_cores\": {cores}, \"arch\": {arch}, \"platform\": {platform} }},\n  \
         \"workload\": {{ \"seed\": {seed}, \"warmup_rounds\": {warmup}, \"measured_rounds\": {rounds}, \
         \"order\": \"rotated: round r starts at case r mod n\", \"quick\": {quick}, \"slowdown\": {{ {slowdown_json} }} }},\n  \
         \"cases\": [\n{cases}\n  ],\n  \"probes\": {{\n    \"lifecycle.memory\": {probe}\n  }}\n}}\n",
        timestamp = json_string(&format!("unix:{timestamp}")),
        version = json_string(vmx::VERSION),
        rustc = json_string(&rustc_version()),
        profile = json_string(if cfg!(debug_assertions) { "debug" } else { "release" }),
        cpu = json_string(&cpu_model()),
        cores = std::thread::available_parallelism().map_or(0, usize::from),
        arch = json_string(std::env::consts::ARCH),
        platform = json_string(std::env::consts::OS),
        seed = options.seed,
        warmup = options.warmup,
        rounds = options.rounds,
        quick = options.quick,
        cases = cases_json.join(",\n"),
    );
    match &options.out {
        Some(path) => std::fs::write(path, report).expect("write report"),
        None => print!("{report}"),
    }
    if SINK.load(Ordering::Relaxed) == u64::MAX {
        eprintln!();
    }
    if !probe_bounded {
        eprintln!("lifecycle.memory probe exceeded its bound");
        std::process::exit(1);
    }
}
