"""Keep each inline tool version equal across its copies (#1838).

Dependabot does not read `run:` text, so an inline version changes only by hand.
These tests read every copy of uv, pip-audit, cargo-audit and npm in the workflows,
and every copy of the mdformat packages in conformance.yml and .pre-commit-config.yaml.
A second value fails the run. The accessibility step runs in the locked Python
environment, so no workflow installs pytest with a version of its own.
"""

import re
from pathlib import Path

import pytest

from .workflow_jobs import run_commands, workflow_job

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Tool -> pattern with one capture group for its version. The uv pattern starts at the
# line start, so it does not match `python-version:`.
INLINE_VERSIONS: dict[str, re.Pattern[str]] = {
    "uv": re.compile(r'^[ \t]+version: "([^"]+)"', re.MULTILINE),
    "pip-audit": re.compile(r"pip-audit==([\w.]+)"),
    "cargo-audit": re.compile(r"cargo-audit --version ([\w.]+)"),
    "npm": re.compile(r"npm@([\w.]+)"),
}
MDFORMAT_PACKAGES = ("mdformat", "mdformat-gfm", "mdformat-tables")
ACCESSIBILITY_TEST = "tools/tests/test_example_accessibility.py"
LOCKED_SYNC = "uv --project langs/python sync --locked --all-extras"


def inline_versions(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Map each tool to a (workflow file name, version) pair for every inline copy."""
    found: dict[str, list[tuple[str, str]]] = {tool: [] for tool in INLINE_VERSIONS}
    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for tool, pattern in INLINE_VERSIONS.items():
            found[tool].extend((workflow.name, version) for version in pattern.findall(text))
    return found


def disagreeing_tools(found: dict[str, list[tuple[str, str]]]) -> set[str]:
    """Return the tools whose copies name more than one version."""
    return {tool for tool, copies in found.items() if len({v for _, v in copies}) > 1}


def mdformat_pins(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return the mdformat pins of conformance.yml and of the pre-commit hook."""
    conformance = (root / ".github/workflows/conformance.yml").read_text(encoding="utf-8")
    step = conformance.split("- name: mdformat check (spec/ + docs/ + CHANGELOGs)", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    ci = dict(re.findall(r'"(mdformat(?:-gfm|-tables)?)==([\w.]+)"', step))

    pre_commit = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = pre_commit.split("repo: https://github.com/executablebooks/mdformat", 1)[1]
    hook = hook.split("\n  - repo:", 1)[0]
    rev = re.search(r"^ +rev: ([\w.]+)$", hook, re.MULTILINE)
    assert rev is not None, "the mdformat hook has no rev"
    pins = dict(re.findall(r"- (mdformat(?:-gfm|-tables)?)==([\w.]+)", hook))
    pins["mdformat"] = rev.group(1)
    return ci, pins


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_each_inline_tool_has_one_version_across_the_workflows() -> None:
    found = inline_versions(REPO_ROOT)

    for tool, copies in found.items():
        assert copies, f"no inline {tool} version found; the pattern or the workflows changed"
    disagreeing = disagreeing_tools(found)
    assert disagreeing == set(), {tool: found[tool] for tool in sorted(disagreeing)}


@pytest.mark.parametrize(
    ("tool", "line"),
    [
        ("uv", '          version: "{}"\n'),
        ("pip-audit", "          uvx --from pip-audit=={} python\n"),
        ("cargo-audit", "          cargo install cargo-audit --version {} --locked\n"),
        ("npm", "          npm install --global npm@{}\n"),
    ],
)
def test_two_copies_of_a_tool_with_different_versions_fail(
    tmp_path: Path, tool: str, line: str
) -> None:
    # The values are placeholders: this test checks agreement, not a pin.
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "first.yml").write_text(line.format("first"), encoding="utf-8")
    (workflows / "second.yml").write_text(line.format("second"), encoding="utf-8")

    assert disagreeing_tools(inline_versions(tmp_path)) == {tool}


def test_no_workflow_installs_pytest_with_an_inline_version() -> None:
    pinned = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if re.search(r"pytest==", path.read_text(encoding="utf-8"))
    ]

    assert pinned == []


def test_example_accessibility_step_runs_in_the_locked_python_environment() -> None:
    commands = run_commands(workflow_job(_read("examples-contract-checks.yml"), "contract"))
    accessibility = [command for command in commands if ACCESSIBILITY_TEST in command]

    assert accessibility == [
        "uv --project langs/python run python tools/check-python-interpreter.py "
        f"--venv langs/python/.venv -- -m pytest {ACCESSIBILITY_TEST} -q"
    ]
    assert LOCKED_SYNC in commands
    assert commands.index(LOCKED_SYNC) < commands.index(accessibility[0])


def test_example_contract_reruns_when_the_locked_python_environment_changes() -> None:
    workflow = _read("examples-contract-checks.yml")
    push = workflow.split("  push:\n", 1)[1].split("\n  pull_request:", 1)[0]

    assert '"langs/python/uv.lock"' in push
    assert '"langs/python/pyproject.toml"' in push


def test_mdformat_pins_match_between_conformance_and_pre_commit() -> None:
    ci, hook = mdformat_pins(REPO_ROOT)

    assert set(ci) == set(MDFORMAT_PACKAGES)
    assert ci == hook


def test_an_mdformat_pin_that_differs_from_the_hook_fails(tmp_path: Path) -> None:
    # The values are placeholders: this test checks agreement, not a pin.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "conformance.yml").write_text(
        "      - name: mdformat check (spec/ + docs/ + CHANGELOGs)\n"
        "        run: |\n"
        '          xargs uv run --with "mdformat==first" --with "mdformat-gfm==first" \\\n'
        '            --with "mdformat-tables==first" python -m mdformat --check\n'
        "      - name: Next step\n",
        encoding="utf-8",
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: https://github.com/executablebooks/mdformat\n"
        "    rev: second\n"
        "    hooks:\n"
        "      - id: mdformat\n"
        "        additional_dependencies:\n"
        "          - mdformat-gfm==first\n"
        "          - mdformat-tables==first\n"
        "  - repo: local\n",
        encoding="utf-8",
    )

    ci, hook = mdformat_pins(tmp_path)

    assert ci["mdformat"] == "first"
    assert hook["mdformat"] == "second"
    assert ci != hook
