"""Unit tests for tools/swift-test-watchdog.py (#533)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
import swift_test_watchdog as watchdog

SCRIPT = Path(__file__).resolve().parents[1] / "swift-test-watchdog.py"

# A stand-in for `swift test --parallel`: a parent that runs one child whose
# arguments carry `-XCTest <case>`, the way SwiftPM runs each case in its own
# `xctest` process, and exits with the child's status.
_PARENT = """
import subprocess, sys
child = [sys.executable, "-c", "import sys, time; time.sleep(float(sys.argv[1]))",
         sys.argv[1], "-XCTest", sys.argv[2]]
sys.exit(subprocess.call(child))
"""


def _run(*args: str, timeout: float = 60) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result, time.monotonic() - started


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("00:05", 5.0), ("12:34", 754.0), ("01:02:03", 3723.0), ("2-01:00:00", 176400.0)],
)
def test_parses_ps_elapsed_times(text: str, seconds: float) -> None:
    assert watchdog.parse_elapsed(text) == seconds


def test_finds_cases_anywhere_below_the_command_by_name() -> None:
    xctest = "/Applications/Xcode.app/Contents/Developer/usr/bin/xctest"
    output = "\n".join(
        [
            "  100     1   05:00 swift test --parallel",
            "  101   100   04:59 swift-package test --parallel",
            f"  102   101   03:00 {xctest} -XCTest Suite.WorkspaceVMTests/testSave /p.xctest",
            f"  103   101   00:01 {xctest} -XCTest Suite.WorkspaceVMTests/testSelect /p.xctest",
            f"  200     1   09:00 {xctest} -XCTest Other.Tests/testUnrelated /q.xctest",
            "  104   102   00:00 /bin/sh -c helper",
        ]
    )
    processes = watchdog.parse_ps(output)

    cases = watchdog.running_cases(processes, 100)

    assert [(info.pid, info.elapsed, name) for info, name in cases] == [
        (102, 180.0, "Suite.WorkspaceVMTests/testSave"),
        (103, 1.0, "Suite.WorkspaceVMTests/testSelect"),
    ]


def test_ignores_processes_without_an_xctest_case() -> None:
    assert watchdog.case_name("swift test --parallel") is None
    assert watchdog.case_name("xctest /p.xctest") is None
    assert watchdog.case_name("tool --no-XCTest Suite/test") is None


def test_kills_and_names_a_hung_case_long_before_it_would_finish() -> None:
    result, elapsed = _run(
        "--per-test-timeout",
        "1",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _PARENT,
        "60",
        "Fake.Suite/testHangs",
    )

    assert result.returncode != 0
    assert "::error::XCTest case Fake.Suite/testHangs ran longer than 1 s" in result.stdout
    assert "::error::Hung XCTest cases: Fake.Suite/testHangs" in result.stdout
    assert elapsed < 30


def test_passes_through_a_suite_that_finishes_in_time() -> None:
    result, _ = _run(
        "--per-test-timeout",
        "30",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _PARENT,
        "0",
        "Fake.Suite/testPasses",
    )

    assert result.returncode == 0
    assert "::error::" not in result.stdout


def test_propagates_the_command_failure() -> None:
    result, _ = _run("--", sys.executable, "-c", "import sys; sys.exit(3)")

    assert result.returncode == 3


def test_bounds_the_whole_command() -> None:
    result, elapsed = _run(
        "--timeout",
        "1",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _PARENT,
        "60",
        "Fake.Suite/testSlow",
    )

    assert result.returncode == 124
    assert "still running: Fake.Suite/testSlow" in result.stdout
    assert elapsed < 30


def test_requires_a_command() -> None:
    result, _ = _run("--per-test-timeout", "1")

    assert result.returncode == 2
    assert "a command is required" in result.stderr


# A stand-in for a single-process `swift test`: one process prints XCTest's
# progress lines for each case in argv[2:], then sleeps argv[1] seconds inside
# the last case without finishing it.
_SINGLE_PROCESS = """
import sys, time
cases = sys.argv[2:]
for case in cases[:-1]:
    print(f"Test Case '-[{case}]' started.", flush=True)
    print(f"Test Case '-[{case}]' passed (0.001 seconds).", flush=True)
print(f"Test Case '-[{cases[-1]}]' started.", flush=True)
time.sleep(float(sys.argv[1]))
print(f"Test Case '-[{cases[-1]}]' passed (1.000 seconds).", flush=True)
"""


@pytest.mark.parametrize(
    ("line", "name"),
    [
        (
            "Test Case '-[VMxTests.CompositeVMTests testA]' started.",
            "VMxTests.CompositeVMTests/testA",
        ),
        ("Test Case 'CompositeVMTests.testA' started at 2026-11-09", "CompositeVMTests.testA"),
    ],
)
def test_reads_the_running_case_from_xctest_output(line: str, name: str) -> None:
    cases = watchdog.OutputCases()

    cases.feed(line, 0.0)

    assert cases.overdue(5.0, 10.0) is None
    assert cases.overdue(10.0, 10.0) == name
    cases.feed(line.replace("started", "failed (9.000 seconds)", 1), 11.0)
    assert cases.overdue(100.0, 10.0) is None


def test_names_a_hung_case_of_a_single_process_run_and_kills_the_run() -> None:
    result, elapsed = _run(
        "--per-test-timeout",
        "1",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _SINGLE_PROCESS,
        "60",
        "Fake.Suite testPasses",
        "Fake.Suite testHangs",
    )

    assert result.returncode == 1
    assert "Test Case '-[Fake.Suite testPasses]' passed" in result.stdout
    assert "::error::XCTest case Fake.Suite/testHangs ran longer than 1 s" in result.stdout
    assert "::error::Hung XCTest cases: Fake.Suite/testHangs" in result.stdout
    assert "testPasses ran longer" not in result.stdout
    assert elapsed < 30


def test_a_single_process_run_whose_cases_finish_in_time_passes() -> None:
    result, _ = _run(
        "--per-test-timeout",
        "30",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _SINGLE_PROCESS,
        "1",
        "Fake.Suite testA",
        "Fake.Suite testB",
    )

    assert result.returncode == 0
    assert "Test Case '-[Fake.Suite testB]' passed" in result.stdout
    assert "::error::" not in result.stdout


# A stand-in for the replayed output of a `--parallel` run: SwiftPM prints a
# crashed case's output, `started` line included, with no `passed` or `failed`
# line after it, and the run goes on.
_PARALLEL_REPLAY = """
import sys, time
print("Test Case '-[Fake.Suite testCrashed]' started.", flush=True)
time.sleep(float(sys.argv[2]))
"""


def test_a_parallel_run_ignores_a_started_line_without_a_finish() -> None:
    result, _ = _run(
        "--per-test-timeout",
        "1",
        "--poll-interval",
        "0.2",
        "--",
        sys.executable,
        "-c",
        _PARALLEL_REPLAY,
        "--parallel",
        "3",
    )

    assert result.returncode == 0
    assert "Test Case '-[Fake.Suite testCrashed]' started." in result.stdout
    assert "::error::" not in result.stdout
