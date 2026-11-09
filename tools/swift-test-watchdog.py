#!/usr/bin/env python3
"""Run a SwiftPM test command and fail fast, by name, when an XCTest case hangs.

`swift test --parallel` runs each test case in its own `xctest` process whose
arguments name the case (`-XCTest Suite/testName`). The watchdog polls the
process tree under the command it starts. A case that outlives
`--per-test-timeout` is sampled (where macOS `sample` exists), killed, and
reported by name, so a hang fails within minutes instead of at the job timeout
(#533).

A single-process `swift test` runs every case in one `xctest` process. There
the watchdog reads the `Test Case '...' started.` and `passed`/`failed` lines
of the command's output. A case that has started and not finished within
`--per-test-timeout` is reported by name, and the whole command is sampled and
killed (#1461). A `--parallel` command skips this output check: SwiftPM
replays a crashed case's output, `started` line included, with no `passed` or
`failed` line after it, and the process-tree check already bounds each case.
`--timeout` bounds the whole command as a backstop.

    python3 tools/swift-test-watchdog.py --per-test-timeout 120 -- swift test --parallel
    python3 tools/swift-test-watchdog.py --per-test-timeout 300 -- swift test
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

_CASE = re.compile(r"(?:^|\s)-XCTest\s+(\S+)")
# XCTest's own progress lines: `Test Case '-[Module.Suite testName]' started.`
# on Darwin, `Test Case 'Suite.testName' started at ...` elsewhere.
_STARTED = re.compile(r"^Test Case '(?P<name>[^']+)' started\b")
_FINISHED = re.compile(r"^Test Case '(?P<name>[^']+)' (?:passed|failed|skipped)\b")
_DARWIN_NAME = re.compile(r"^-\[(?P<suite>\S+) (?P<test>\S+)\]$")
# `-ww`: without it, ps truncates arguments to the terminal width or 80 columns.
_PS = ["ps", "-A", "-ww", "-o", "pid=,ppid=,etime=,args="]


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    elapsed: float
    args: str


def parse_elapsed(text: str) -> float:
    """Parse a `ps` elapsed time, `[[dd-]hh:]mm:ss`, into seconds."""
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    parts = [int(part) for part in text.split(":")]
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"unrecognized elapsed time: {text!r}")
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def parse_ps(output: str) -> list[ProcessInfo]:
    """Parse `ps -A -o pid=,ppid=,etime=,args=` output."""
    processes = []
    for line in output.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 3:
            continue
        try:
            pid, ppid, elapsed = int(fields[0]), int(fields[1]), parse_elapsed(fields[2])
        except ValueError:
            continue
        processes.append(ProcessInfo(pid, ppid, elapsed, fields[3] if len(fields) > 3 else ""))
    return processes


def descendants(processes: list[ProcessInfo], root: int) -> list[ProcessInfo]:
    """Every process below `root`, whatever its process group."""
    children: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        children.setdefault(process.ppid, []).append(process)
    found: list[ProcessInfo] = []
    pending = [root]
    seen = {root}
    while pending:
        for child in children.get(pending.pop(), []):
            if child.pid not in seen:
                seen.add(child.pid)
                found.append(child)
                pending.append(child.pid)
    return found


def case_name(args: str) -> str | None:
    """The XCTest case an `xctest` process runs, from its `-XCTest` argument."""
    match = _CASE.search(args)
    return match.group(1) if match else None


def running_cases(processes: list[ProcessInfo], root: int) -> list[tuple[ProcessInfo, str]]:
    """The XCTest cases running below `root`, with their processes."""
    cases = []
    for process in descendants(processes, root):
        name = case_name(process.args)
        if name is not None:
            cases.append((process, name))
    return cases


def output_case_name(name: str) -> str:
    """`-[Module.Suite testName]` as `Module.Suite/testName`, the `-XCTest` form."""
    match = _DARWIN_NAME.match(name)
    return f"{match.group('suite')}/{match.group('test')}" if match else name


class OutputCases:
    """Tracks the XCTest case that a single-process run is executing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: tuple[str, float] | None = None

    def feed(self, line: str, now: float) -> None:
        started = _STARTED.match(line)
        if started:
            with self._lock:
                self._current = (output_case_name(started.group("name")), now)
            return
        finished = _FINISHED.match(line)
        if finished:
            with self._lock:
                name = output_case_name(finished.group("name"))
                if self._current is not None and self._current[0] == name:
                    self._current = None

    def overdue(self, now: float, timeout: float) -> str | None:
        """The running case's name when it has run longer than `timeout`."""
        with self._lock:
            if self._current is not None and now - self._current[1] >= timeout:
                return self._current[0]
        return None


def relay(stream: IO[bytes], cases: OutputCases | None) -> None:
    """Copy the command's output to ours and record XCTest case progress."""
    for raw in iter(stream.readline, b""):
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
        if cases is not None:
            cases.feed(raw.decode("utf-8", errors="replace").rstrip("\r\n"), time.monotonic())


def snapshot() -> list[ProcessInfo]:
    result = subprocess.run(_PS, capture_output=True, text=True, timeout=30, check=False)
    return parse_ps(result.stdout)


def sample(pid: int) -> None:
    """Print the thread stacks of a hung process where macOS `sample` exists."""
    if shutil.which("sample") is None:
        return
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / f"sample-{pid}.txt"
        try:
            subprocess.run(
                ["sample", str(pid), "3", "-mayDie", "-file", str(report)],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return
        if report.exists():
            print(f"::group::sample of pid {pid}", flush=True)
            print(report.read_text(encoding="utf-8", errors="replace"), flush=True)
            print("::endgroup::", flush=True)


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_tree(root: int) -> None:
    for process in descendants(snapshot(), root):
        kill(process.pid)
    try:
        os.killpg(root, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a SwiftPM test command; kill and name any XCTest case that hangs."
    )
    parser.add_argument(
        "--per-test-timeout",
        type=float,
        default=120.0,
        help="seconds one XCTest case may run before it is sampled and killed",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1200.0,
        help="seconds the whole command may run before it is killed",
    )
    parser.add_argument("--poll-interval", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    started = time.monotonic()
    # XCTest writes its progress lines unbuffered when NSUnbufferedIO is set,
    # as Xcode sets it, so a case's `started` line is not held in a pipe buffer.
    process = subprocess.Popen(
        command,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "NSUnbufferedIO": "YES"},
    )
    assert process.stdout is not None
    # A `--parallel` run is bounded per case by the process tree; its replayed
    # output can hold a `started` line that never finishes (a crashed case).
    cases = None if "--parallel" in command else OutputCases()
    reader = threading.Thread(target=relay, args=(process.stdout, cases), daemon=True)
    reader.start()
    hung: dict[int, str] = {}
    try:
        while process.poll() is None:
            processes = snapshot()
            if time.monotonic() - started > args.timeout:
                names = sorted({name for _, name in running_cases(processes, process.pid)})
                running = ", ".join(names) if names else "no XCTest case found"
                print(
                    f"::error::{' '.join(command)} ran longer than {args.timeout:g} s; "
                    f"still running: {running}",
                    flush=True,
                )
                kill_tree(process.pid)
                process.wait()
                return 124
            for info, name in running_cases(processes, process.pid):
                if info.pid in hung or info.elapsed < args.per_test_timeout:
                    continue
                hung[info.pid] = name
                print(
                    f"::error::XCTest case {name} ran longer than "
                    f"{args.per_test_timeout:g} s; killing pid {info.pid}",
                    flush=True,
                )
                sample(info.pid)
                kill(info.pid)
            name = None if cases is None else cases.overdue(time.monotonic(), args.per_test_timeout)
            if name is not None:
                print(
                    f"::error::XCTest case {name} ran longer than "
                    f"{args.per_test_timeout:g} s; killing {' '.join(command)}",
                    flush=True,
                )
                for info in descendants(processes, process.pid):
                    if "xctest" in info.args:
                        sample(info.pid)
                kill_tree(process.pid)
                process.wait()
                reader.join(timeout=10)
                print(f"::error::Hung XCTest cases: {name}", flush=True)
                return 1
            time.sleep(args.poll_interval)
    except BaseException:
        kill_tree(process.pid)
        raise
    reader.join(timeout=10)

    if hung:
        print(f"::error::Hung XCTest cases: {', '.join(sorted(set(hung.values())))}", flush=True)
        return process.returncode or 1
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
