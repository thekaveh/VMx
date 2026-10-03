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
