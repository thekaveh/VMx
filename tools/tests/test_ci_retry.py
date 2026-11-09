"""Tests for tools/ci-retry.mjs and the workflow steps that use it (#1360)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "ci-retry.mjs"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
HELPER = 'node "${{ github.workspace }}/tools/ci-retry.mjs"'

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Fails while the counter file holds fewer than argv[2] marks, printing argv[3].
_FLAKY = """
import sys
from pathlib import Path
counter = Path(sys.argv[1])
count = len(counter.read_text()) if counter.exists() else 0
counter.write_text("x" * (count + 1))
if count < int(sys.argv[2]):
    print(sys.argv[3], flush=True)
    sys.exit(7)
print("installed", flush=True)
"""


def _run(*args: str, timeout: float = 60) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    result = subprocess.run(
        ["node", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result, time.monotonic() - started


def _flaky(counter: Path, failures: int, message: str) -> list[str]:
    return [sys.executable, "-c", _FLAKY, str(counter), str(failures), message]


@needs_node
def test_a_command_that_fails_twice_then_succeeds_passes_on_the_third_attempt(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "count"
    result, _ = _run("--delay=0", *_flaky(counter, 2, "boom"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert counter.read_text() == "xxx"
    assert "attempt 3 of 3" in result.stdout
    assert "installed" in result.stdout


@needs_node
def test_a_command_that_always_fails_exits_with_the_last_attempt_status(tmp_path: Path) -> None:
    counter = tmp_path / "count"
    result, _ = _run("--delay=0", "--attempts=3", *_flaky(counter, 99, "boom"))

    assert result.returncode == 7
    assert counter.read_text() == "xxx"
    assert "3 attempts failed; exiting 7" in result.stdout


@needs_node
def test_attempts_wait_for_the_delay(tmp_path: Path) -> None:
    result, elapsed = _run("--delay=1", "--attempts=2", *_flaky(tmp_path / "c", 99, "boom"))

    assert result.returncode == 7
    assert elapsed >= 1


@needs_node
@pytest.mark.parametrize(
    "message",
    [
        "npm error audit endpoint returned an error",
        "npm error code ECONNRESET",
        "npm error code E503",
        "npm error 503 Service Unavailable - GET https://registry.npmjs.org/x",
    ],
)
def test_npm_network_errors_are_retried(tmp_path: Path, message: str) -> None:
    counter = tmp_path / "count"
    result, _ = _run("--delay=0", "--retry-on=npm-network", *_flaky(counter, 1, message))

    assert result.returncode == 0, result.stdout + result.stderr
    assert counter.read_text() == "xx"


@needs_node
def test_an_npm_audit_advisory_finding_fails_after_one_attempt(tmp_path: Path) -> None:
    counter = tmp_path / "count"
    report = "# npm audit report\nleft-pad  <1.3.0\nSeverity: high\n1 high severity vulnerability"
    result, _ = _run("--delay=0", "--retry-on=npm-network", *_flaky(counter, 99, report))

    assert result.returncode == 7
    assert counter.read_text() == "x"
    assert "Severity: high" in result.stdout
    assert "without a npm-network error; not retrying" in result.stdout


@needs_node
def test_an_attempt_that_runs_too_long_is_killed_and_retried() -> None:
    result, elapsed = _run(
        "--delay=0",
        "--attempts=2",
        "--attempt-timeout=1",
        "--retry-on=npm-network",
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
    )

    assert result.returncode == 124
    assert result.stdout.count("ran longer than 1 s") == 2
    assert elapsed < 30


@needs_node
@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "a command is required"),
        (("--attempts", "npm", "ci"), "write options as --attempts=VALUE"),
        (("--attempts=0", "npm"), "--attempts needs a number of at least 1"),
        (("--retry-on=anything", "npm"), "unknown --retry-on filter"),
        (("--bogus=1", "npm"), "unknown option --bogus"),
    ],
)
def test_rejects_bad_arguments(args: tuple[str, ...], message: str) -> None:
    result, _ = _run(*args)

    assert result.returncode == 2
    assert message in result.stderr


def _defaults() -> dict[str, float]:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"const DEFAULTS = Object\.freeze\(\{ (?P<body>[^}]*) \}\);", text)
    assert match is not None
    return {
        key.strip(): float(value)
        for key, value in (pair.split(":") for pair in match.group("body").split(","))
    }


def helper_budget_seconds(call: str) -> float:
    """Worst-case seconds of one helper call: every attempt times out."""
    options = _defaults()
    names = {"attempts": "attempts", "delay": "delay", "attempt-timeout": "attemptTimeout"}
    for name, value in re.findall(r"--(attempts|delay|attempt-timeout)=(\S+)", call):
        options[names[name]] = float(value)
    attempts = options["attempts"]
    return attempts * options["attemptTimeout"] + (attempts - 1) * options["delay"]


def _jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", maxsplit=1)[1]
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _steps(job: str) -> list[str]:
    return re.split(r"(?m)^      - ", job)[1:]


def test_every_npm_ci_and_npm_audit_in_the_workflows_runs_through_the_helper() -> None:
    calls = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for match in re.finditer(r"(?<![\w/.-])npm (?:ci|audit)(?= |$)", line):
                prefix = line[: match.start()]
                assert prefix.endswith(f"{HELPER} --retry-on=npm-network "), (
                    f"{path.name}:{number}: {line.strip()}"
                )
                calls += 1
    assert calls >= 20


def test_each_retried_step_fits_inside_its_job_timeout() -> None:
    checked = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in _jobs(path.read_text(encoding="utf-8")).items():
            timeout = re.search(r"(?m)^    timeout-minutes: (\d+)$", job)
            for step in _steps(job):
                calls = [line for line in step.splitlines() if HELPER in line]
                if not calls:
                    continue
                assert timeout is not None, f"{path.name}:{name} has no timeout"
                budget = sum(helper_budget_seconds(call) for call in calls)
                assert budget < int(timeout.group(1)) * 60, (
                    f"{path.name}:{name}: retried step needs up to {budget:g} s"
                )
                checked += 1
    assert checked >= 20


def test_helper_budget_reads_explicit_options_over_the_defaults() -> None:
    defaults = _defaults()
    assert helper_budget_seconds(f"{HELPER} npm ci") == (
        defaults["attempts"] * defaults["attemptTimeout"]
        + (defaults["attempts"] - 1) * defaults["delay"]
    )
    assert helper_budget_seconds(f"{HELPER} --attempts=2 --delay=5 --attempt-timeout=60 x") == 125


def test_codeql_init_runs_a_second_attempt_only_after_the_first_fails() -> None:
    workflow = (WORKFLOWS / "security-audit.yml").read_text(encoding="utf-8")
    job = _jobs(workflow)["codeql"]
    steps = _steps(job)
    inits = [step for step in steps if "uses: github/codeql-action/init@" in step]
    assert len(inits) == 2
    first, second = inits
    assert "id: codeql-init\n" in first
    assert "continue-on-error: true\n" in first
    assert "if:" not in first
    assert "if: steps.codeql-init.outcome != 'success'\n" in second
    assert "continue-on-error" not in second
    wait = steps[steps.index(first) + 1]
    assert "if: steps.codeql-init.outcome != 'success'\n" in wait
    assert "run: sleep 60" in wait
    assert steps.index(second) == steps.index(first) + 2
    step_limits = "".join((first, wait, second))
    minutes = sum(int(m) for m in re.findall(r"timeout-minutes: (\d+)", step_limits))
    job_minutes = re.search(r"(?m)^    timeout-minutes: (\d+)$", job)
    assert job_minutes is not None
    assert minutes < int(job_minutes.group(1))
