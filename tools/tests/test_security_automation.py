"""Repository security automation contracts."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependabot_covers_every_committed_dependency_ecosystem() -> None:
    config = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    for ecosystem in ("cargo", "github-actions", "npm", "nuget", "pip", "uv"):
        assert config.count(f"package-ecosystem: {ecosystem}") == 1
    assert config.count("interval: weekly") == 6


def test_weekly_audit_covers_every_committed_lock_family() -> None:
    workflow = (REPO_ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")

    assert 'cron: "23 6 * * 1"' in workflow
    assert "--no-emit-local" in workflow
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
