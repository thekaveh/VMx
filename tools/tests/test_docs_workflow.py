"""Contract checks for documentation workflow change detection."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "docs.yml"


def test_docs_workflow_watches_every_current_facing_markdown_area() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    for path in (
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "compatibility-matrix.md",
        "examples/**/*.md",
        "langs/**/*.md",
        "tools/**/*.md",
    ):
        assert workflow.count(f'- "{path}"') == 2, (
            f"{path} must trigger docs validation on push and pull_request"
        )
