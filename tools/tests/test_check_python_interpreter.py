"""Exercise interpreter assertions across real process and virtualenv boundaries."""

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "check-python-interpreter.py"
VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"


@pytest.fixture(scope="module")
def interpreter(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("identity") / "venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(root)
    return root, root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_helper(interpreter: tuple[Path, Path], *args: str) -> subprocess.CompletedProcess[str]:
    root, python = interpreter
    return subprocess.run(
        [str(python), str(HELPER), "--expected-version", VERSION, "--venv", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_reports_identity_to_stderr(interpreter: tuple[Path, Path]) -> None:
    result = run_helper(interpreter)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    for value in (VERSION, str(interpreter[0]), str(interpreter[1])):
        assert value in result.stderr


@pytest.mark.parametrize(
    "bad_args, message",
    [
        (["--expected-version", "0.0"], "version mismatch"),
        (["--venv", "different-venv"], "prefix mismatch"),
        (["--expected-executable", "different-python"], "executable mismatch"),
    ],
)
def test_rejects_mismatch_before_child(
    interpreter: tuple[Path, Path], bad_args: list[str], message: str
) -> None:
    result = run_helper(interpreter, *bad_args, "--", "-c", "print('CHILD RAN')")
    assert result.returncode != 0
    assert message in result.stderr
    assert "CHILD RAN" not in result.stdout


def test_child_uses_asserted_python_and_preserves_arguments(interpreter: tuple[Path, Path]) -> None:
    result = run_helper(
        interpreter,
        "--expected-executable",
        str(interpreter[1]),
        "--",
        "-c",
        "import json,sys; print(json.dumps([sys.executable, sys.prefix, sys.argv[1:]]))",
        "space and $literal",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        str(interpreter[1]),
        str(interpreter[0]),
        ["space and $literal"],
    ]


def test_child_failure_is_preserved(interpreter: tuple[Path, Path]) -> None:
    result = run_helper(interpreter, "--", "-c", "raise SystemExit(23)")
    assert result.returncode == 23


def test_distinct_venv_symlinks_do_not_collapse(
    interpreter: tuple[Path, Path], tmp_path: Path
) -> None:
    other = tmp_path / "other"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(other)
    if os.name != "nt":
        assert interpreter[1].resolve() == (other / "bin/python").resolve()
    result = run_helper(interpreter, "--venv", str(other), "--", "-c", "print('CHILD RAN')")
    assert result.returncode != 0
    assert "prefix mismatch" in result.stderr
    assert not result.stdout


def test_lexically_equivalent_paths_are_accepted(interpreter: tuple[Path, Path]) -> None:
    result = run_helper(interpreter, "--venv", str(interpreter[0] / ".." / "venv"))
    assert result.returncode == 0, result.stderr


def test_captures_initial_executable_for_later_steps(
    interpreter: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    result = run_helper(interpreter, "--capture-output")
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"executable={interpreter[1]}\n"


def test_tool_context_requires_explicit_opt_in() -> None:
    common = [sys.executable, str(HELPER), "--expected-version", VERSION]
    missing = subprocess.run(common, capture_output=True, text=True, check=False, timeout=30)
    assert missing.returncode != 0
    explicit = subprocess.run(
        [*common, "--tool-context", "--", "-c", "print('tool')"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert explicit.returncode == 0, explicit.stderr
    assert explicit.stdout == "tool\n"


def test_empty_captured_executable_is_rejected(interpreter: tuple[Path, Path]) -> None:
    result = run_helper(interpreter, "--expected-executable", "", "--", "-c", "print('CHILD RAN')")
    assert result.returncode != 0
    assert "executable mismatch" in result.stderr
    assert not result.stdout


def test_script_runs_with_asserted_identity(interpreter: tuple[Path, Path], tmp_path: Path) -> None:
    script = tmp_path / "child script.py"
    script.write_text("import sys; print(sys.executable); print(sys.argv[1])\n")
    result = run_helper(interpreter, "--", str(script), "two words")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(interpreter[1]), "two words"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX Python launcher aliases")
def test_accepts_python3_launcher_within_the_venv(interpreter: tuple[Path, Path]) -> None:
    launcher = interpreter[1].with_name("python3")
    result = subprocess.run(
        [str(launcher), str(HELPER), "--expected-version", VERSION, "--venv", str(interpreter[0])],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert str(launcher) in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory symlinks")
def test_accepts_alias_of_containing_directory(
    interpreter: tuple[Path, Path], tmp_path: Path
) -> None:
    alias = tmp_path / "parent-alias"
    alias.symlink_to(interpreter[0].parent, target_is_directory=True)
    expected_root = alias / interpreter[0].name
    result = run_helper(
        interpreter,
        "--venv",
        str(expected_root),
        "--expected-executable",
        str(expected_root / "bin/python"),
    )
    assert result.returncode == 0, result.stderr
