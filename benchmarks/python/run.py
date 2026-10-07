"""VMx Python benchmark harness.

Method and report format: docs/content/performance-methodology.md. Run from
the repository root with the Python flavor's environment:

    uv run --project langs/python python benchmarks/python/run.py --out report.json
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import vmx
from vmx import (
    ComponentVMOf,
    MessageHub,
    NullDispatcher,
    ObservableList,
    PropertyChangedMessage,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Case:
    id: str
    params: dict[str, Any]
    ops: int
    setup: Callable[[], dict[str, Any]]
    run: Callable[[dict[str, Any]], None]
    teardown: Callable[[dict[str, Any]], None] = lambda state: None
    samples: list[float] = field(default_factory=list)


def parse_slowdown() -> dict[str, int]:
    """VMX_BENCH_SLOWDOWN="case-id=iterations" adds a fixed spin per operation.

    Case ids contain "=" themselves, so the count follows the last one.
    """
    slowdown: dict[str, int] = {}
    for entry in filter(None, os.environ.get("VMX_BENCH_SLOWDOWN", "").split(",")):
        case_id, _, iterations = entry.rpartition("=")
        if not case_id or not iterations.isdigit():
            raise SystemExit(f"VMX_BENCH_SLOWDOWN entry {entry!r} is not case-id=iterations")
        slowdown[case_id] = int(iterations)
    return slowdown


SLOWDOWN = parse_slowdown()


def spinner(case_id: str) -> Callable[[], None]:
    iterations = SLOWDOWN.get(case_id, 0)
    if iterations == 0:
        return lambda: None

    def spin() -> None:
        total = 0
        for index in range(iterations):
            total = (total + index) % 1_000_003

    return spin


def lcg(seed: int) -> Callable[[], int]:
    state = seed & 0xFFFFFFFF

    def next_value() -> int:
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        return state

    return next_value


SENDER = object()
MESSAGE = PropertyChangedMessage(SENDER, "bench", "value")


def subscribe(hub: MessageHub[Any], count: int) -> list[Any]:
    return [hub.messages.subscribe(lambda _message: None) for _ in range(count)]


def release(state: dict[str, Any]) -> None:
    for subscription in state.get("subscriptions", []):
        subscription.dispose()
    if "vm" in state:
        state["vm"].dispose()
    state["hub"].dispose()


def send_case(subscribers: int, messages: int) -> Case:
    case_id = f"hub.send/subscribers={subscribers}"

    def setup() -> dict[str, Any]:
        hub: MessageHub[Any] = MessageHub()
        return {"hub": hub, "subscriptions": subscribe(hub, subscribers), "spin": spinner(case_id)}

    def run(state: dict[str, Any]) -> None:
        send, spin = state["hub"].send, state["spin"]
        for _ in range(messages):
            send(MESSAGE)
            spin()

    return Case(
        case_id, {"subscribers": subscribers, "messages": messages}, messages, setup, run, release
    )


def observer_case(mode: str, messages: int) -> Case:
    case_id = f"hub.observer/{mode}"

    def setup() -> dict[str, Any]:
        hub: MessageHub[Any] = MessageHub()
        subscriptions = []
        if mode == "active":
            seen: list[str] = []

            def observe(message: Any) -> None:
                seen.append(type(message).__name__)
                if len(seen) > 1024:
                    seen.clear()

            subscriptions.append(hub.messages.subscribe(observe))
        return {"hub": hub, "subscriptions": subscriptions, "spin": spinner(case_id)}

    def run(state: dict[str, Any]) -> None:
        send, spin = state["hub"].send, state["spin"]
        for _ in range(messages):
            send(MESSAGE)
            spin()

    return Case(case_id, {"mode": mode, "messages": messages}, messages, setup, run, release)


def batch_case(batch_size: int, messages: int) -> Case:
    case_id = f"hub.batch/size={batch_size}"
    batches = max(1, round(messages / batch_size))

    def setup() -> dict[str, Any]:
        hub: MessageHub[Any] = MessageHub()
        return {"hub": hub, "subscriptions": subscribe(hub, 1), "spin": spinner(case_id)}

    def run(state: dict[str, Any]) -> None:
        hub, spin = state["hub"], state["spin"]
        for _ in range(batches):
            with hub.batch():
                for _ in range(batch_size):
                    hub.send(MESSAGE)
                    spin()

    params = {"batch_size": batch_size, "batches": batches, "subscribers": 1}
    return Case(case_id, params, batches * batch_size, setup, run, release)


def property_case(assignments: int, seed: int) -> Case:
    case_id = "property.set"

    def setup() -> dict[str, Any]:
        hub: MessageHub[Any] = MessageHub()
        vm = ComponentVMOf.create(name="bench", model=0, hub=hub, dispatcher=NullDispatcher())
        next_value = lcg(seed)
        values = [index * 2 + next_value() % 2 + 1 for index in range(assignments)]
        return {
            "hub": hub,
            "vm": vm,
            "values": values,
            "subscriptions": subscribe(hub, 1),
            "spin": spinner(case_id),
        }

    def run(state: dict[str, Any]) -> None:
        vm, spin = state["vm"], state["spin"]
        for value in state["values"]:
            vm.model = value
            spin()

    return Case(
        case_id, {"assignments": assignments, "subscribers": 1}, assignments, setup, run, release
    )


def collection_case(operation: str, length: int, total_ops: int) -> Case:
    case_id = f"collection.{operation}/size={length}"
    repetitions = max(1, round(total_ops / length))

    def setup() -> dict[str, Any]:
        return {"spin": spinner(case_id)}

    def run(state: dict[str, Any]) -> None:
        spin = state["spin"]
        for _ in range(repetitions):
            items: ObservableList[int] = ObservableList()
            for index in range(length):
                if operation == "push":
                    items.append(index)
                else:
                    items.insert(0, index)
                spin()

    params = {"operation": operation, "size": length, "repetitions": repetitions}
    return Case(case_id, params, repetitions * length, setup, run)


def lifecycle_case(cycles: int) -> Case:
    case_id = "lifecycle.construct_dispose"

    def setup() -> dict[str, Any]:
        hub: MessageHub[Any] = MessageHub()
        return {"hub": hub, "subscriptions": subscribe(hub, 1), "spin": spinner(case_id)}

    def run(state: dict[str, Any]) -> None:
        hub, spin, dispatcher = state["hub"], state["spin"], NullDispatcher()
        for cycle in range(cycles):
            vm = ComponentVMOf.create(name="cycle", model=cycle, hub=hub, dispatcher=dispatcher)
            vm.construct()
            vm.dispose()
            spin()

    return Case(case_id, {"cycles": cycles}, cycles, setup, run, release)


def measure(case: Case) -> float:
    state = case.setup()
    gc.collect()
    start = time.perf_counter_ns()
    case.run(state)
    elapsed = time.perf_counter_ns() - start
    case.teardown(state)
    return elapsed / case.ops


def summarize(samples: list[float]) -> dict[str, float]:
    median = statistics.median(samples)
    mad = statistics.median(abs(value - median) for value in samples)
    return {
        "median": median,
        "mad": mad,
        "rel_mad": 0.0 if median == 0 else mad / median,
        "min": min(samples),
        "max": max(samples),
    }


def lifecycle_memory_probe(batches: int, cycles_per_batch: int) -> dict[str, Any]:
    """Bounded memory and queue depth over repeated construct/dispose cycles."""
    hub: MessageHub[Any] = MessageHub()
    delivered = 0

    def count(_message: Any) -> None:
        nonlocal delivered
        delivered += 1

    subscription = hub.messages.subscribe(count)
    dispatcher = NullDispatcher()
    tracemalloc.start()
    gc.collect()
    retained = [tracemalloc.get_traced_memory()[0]]
    max_queue_depth = 0
    for _ in range(batches):
        for cycle in range(cycles_per_batch):
            vm = ComponentVMOf.create(name="probe", model=cycle, hub=hub, dispatcher=dispatcher)
            vm.construct()
            vm.dispose()
        before = delivered
        hub.send(MESSAGE)
        max_queue_depth = max(max_queue_depth, 1 - (delivered - before))
        gc.collect()
        retained.append(tracemalloc.get_traced_memory()[0])
    tracemalloc.stop()
    subscription.dispose()
    hub.dispose()
    # The first batch is warm-up (caches and interned objects); growth is
    # measured across the remaining batches, where a per-cycle leak would show.
    growth = retained[-1] - retained[1]
    limit = 2 * 1024 * 1024
    return {
        "cycles": batches * cycles_per_batch,
        "warmup_batches": 1,
        "retained_bytes_samples": retained,
        "retained_growth_bytes": growth,
        "retained_growth_limit_bytes": limit,
        "bounded": growth < limit and max_queue_depth == 0,
        "max_queue_depth": max_queue_depth,
        "hub_history_size": 0,
        "hub_history_note": "Python hubs retain no delivered messages",
    }


def git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out")
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--only")
    parser.add_argument("--quick", action="store_true")
    options = parser.parse_args()
    if options.quick:
        options.rounds, options.warmup = 3, 1
    scale = 0.05 if options.quick else 1.0

    def size(count: int) -> int:
        return max(1, round(count * scale))

    cases = [
        send_case(0, size(30_000)),
        send_case(1, size(30_000)),
        send_case(100, size(3_000)),
        observer_case("plain", size(30_000)),
        observer_case("active", size(30_000)),
        batch_case(100, size(20_000)),
        batch_case(1000, size(20_000)),
        property_case(size(20_000), options.seed),
        collection_case("push", 1_000, size(100_000)),
        collection_case("push", 10_000, size(100_000)),
        collection_case("push", 100_000, size(100_000)),
        collection_case("insert0", 1_000, size(20_000)),
        collection_case("insert0", 10_000, size(20_000)),
        lifecycle_case(size(5_000)),
    ]
    unknown = sorted(set(SLOWDOWN) - {case.id for case in cases})
    if unknown:
        raise SystemExit(f"VMX_BENCH_SLOWDOWN names unknown cases: {', '.join(unknown)}")
    if options.only:
        cases = [case for case in cases if case.id.startswith(options.only)]

    for round_index in range(options.warmup + options.rounds):
        for offset in range(len(cases)):
            case = cases[(round_index + offset) % len(cases)]
            value = measure(case)
            if round_index >= options.warmup:
                case.samples.append(value)

    probe = (
        lifecycle_memory_probe(6, 500 if options.quick else 5_000)
        if not options.only
        else {"skipped": "--only"}
    )
    package_version = vmx.__version__
    report = {
        "schema": "vmx-bench/1",
        "flavor": "python",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "package_version": package_version,
        "runtime": {
            "name": platform.python_implementation().lower(),
            "version": platform.python_version(),
        },
        "hardware": {
            "cpu_model": cpu_model(),
            "logical_cores": os.cpu_count(),
            "arch": platform.machine(),
            "platform": sys.platform,
            "os_release": platform.release(),
        },
        "workload": {
            "seed": options.seed,
            "warmup_rounds": options.warmup,
            "measured_rounds": options.rounds,
            "order": "rotated: round r starts at case r mod n",
            "quick": options.quick,
            "gc_between_cases": True,
            "slowdown": SLOWDOWN,
        },
        "cases": [
            {
                "id": case.id,
                "unit": "ns/op",
                "params": case.params,
                "ops": case.ops,
                **summarize(case.samples),
                "samples": case.samples,
            }
            for case in cases
        ],
        "probes": {"lifecycle.memory": probe},
    }
    text = json.dumps(report, indent=2) + "\n"
    if options.out:
        Path(options.out).write_text(text)
    else:
        sys.stdout.write(text)
    for entry in report["cases"]:
        print(
            f"{entry['id']:<36} {entry['median']:>10.1f} ns/op  ±{entry['rel_mad'] * 100:.1f}%",
            file=sys.stderr,
        )
    if probe.get("bounded") is False:
        print("lifecycle.memory probe exceeded its bound", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
