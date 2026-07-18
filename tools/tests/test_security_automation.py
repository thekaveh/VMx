"""Repository security automation contracts."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependabot_covers_every_committed_dependency_ecosystem() -> None:
    config = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    sections = dict(
        re.findall(
            r"^  - package-ecosystem: (\S+)\n(.*?)(?=^  - package-ecosystem:|\Z)",
            config,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    expected_directories = {
        "github-actions": {"/"},
        "npm": {
            "/langs/typescript",
            "/examples/typescript/console/hello-vmx",
            "/examples/typescript/react/notes-showcase",
        },
        "cargo": {
            "/langs/rust",
            "/examples/rust/console/hello-vmx",
            "/examples/rust/tui/notes-showcase",
        },
        "uv": {
            "/langs/python",
            "/examples/python",
            "/examples/python/textual/inspector",
            "/examples/python/textual/notes_showcase",
        },
        "pip": {"/docs"},
        "nuget": {"/langs/csharp", "/examples/csharp"},
    }
    assert set(sections) == set(expected_directories)
    for ecosystem, expected in expected_directories.items():
        directories = set(re.findall(r"^      - (/\S*)$", sections[ecosystem], flags=re.MULTILINE))
        directory = re.search(r"^    directory: (/\S*)$", sections[ecosystem], re.MULTILINE)
        if directory is not None:
            directories.add(directory.group(1))
        assert directories == expected
        assert "target-branch: develop" in sections[ecosystem]
        if len(expected) > 1:
            assert "group-by: dependency-name" in sections[ecosystem]
    assert config.count("interval: weekly") == 6


def test_dependabot_changes_run_the_automation_contracts() -> None:
    workflow = (REPO_ROOT / ".github/workflows/conformance.yml").read_text(encoding="utf-8")

    assert workflow.count('      - ".github/dependabot.yml"') == 2


def test_weekly_audit_covers_every_committed_lock_family() -> None:
    workflow = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")

    assert 'cron: "23 6 * * 1"' in workflow
    assert "  pull_request:" in workflow
    for dependency_path in (
        '      - "**/Cargo.lock"',
        '      - "**/Cargo.toml"',
        '      - "**/package-lock.json"',
        '      - "**/package.json"',
        '      - "**/pyproject.toml"',
        '      - "**/uv.lock"',
        '      - "**/*.csproj"',
        '      - "**/packages.lock.json"',
        '      - "docs/requirements.in"',
        '      - "docs/requirements.txt"',
    ):
        assert dependency_path in workflow
    assert "--no-emit-local" in workflow
    assert workflow.count('"-warnaserror:NU1901;NU1902;NU1903;NU1904"') == 2
    assert "dotnet list" not in workflow
    for relative in (
        "langs/typescript",
        "examples/typescript/console/hello-vmx",
        "examples/typescript/react/notes-showcase",
        "langs/rust/Cargo.lock",
        "examples/rust/console/hello-vmx/Cargo.lock",
        "examples/rust/tui/notes-showcase/Cargo.lock",
        "langs/python",
        "examples/python",
        "examples/python/textual/inspector",
        "examples/python/textual/notes_showcase",
        "docs/requirements.txt",
        "langs/csharp/VMx.sln",
        "examples/csharp/Examples.sln",
    ):
        assert relative in workflow

    assert workflow.startswith("name: security-audit\n\npermissions:\n  contents: read\n")


def test_release_workflow_defaults_to_read_only() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert workflow.startswith("name: release\n\npermissions:\n  contents: read\n")
