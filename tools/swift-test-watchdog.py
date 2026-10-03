#!/usr/bin/env python3
"""Run a SwiftPM test command and fail fast, by name, when an XCTest case hangs.

`swift test --parallel` runs each test case in its own `xctest` process whose
arguments name the case (`-XCTest Suite/testName`). The watchdog polls the
process tree under the command it starts. A case that outlives
`--per-test-timeout` is sampled (where macOS `sample` exists), killed, and
reported by name, so a hang fails within minutes instead of at the job timeout
(#533). `--timeout` bounds the whole command as a backstop.

    python3 tools/swift-test-watchdog.py --per-test-timeout 120 -- swift test --parallel
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
import time
from dataclasses import dataclass
from pathlib import Path

_CASE = re.compile(r"(?:^|\s)-XCTest\s+(\S+)")
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
    process = subprocess.Popen(command, start_new_session=True)
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
            time.sleep(args.poll_interval)
    except BaseException:
        kill_tree(process.pid)
        raise

    if hung:
        print(f"::error::Hung XCTest cases: {', '.join(sorted(set(hung.values())))}", flush=True)
        return process.returncode or 1
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
