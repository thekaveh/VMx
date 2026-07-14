"""Regression checks for the generated-wiki publication workflow."""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "wiki.yml"
_CONFORMANCE_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "conformance.yml"


def _conditions(workflow: str) -> list[str]:
    """Return single-line and folded YAML ``if`` expressions."""
    lines = workflow.splitlines()
    conditions: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)if:\s*(.*)$", line)
        if match is None:
            continue
        expression = match.group(2)
        if expression in {"|", "|-", ">", ">-"}:
            indentation = len(match.group(1))
            continuation: list[str] = []
            for following in lines[index + 1 :]:
                if following and len(following) - len(following.lstrip()) <= indentation:
                    break
                continuation.append(following.strip())
            expression = " ".join(continuation)
        conditions.append(expression)
    return conditions


def test_wiki_workflow_does_not_reference_secrets_in_conditions() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert all("secrets." not in condition for condition in _conditions(workflow))
    assert "WIKI_DEPLOY_KEY_VALUE: ${{ secrets.WIKI_DEPLOY_KEY }}" in workflow


def test_wiki_workflow_changes_trigger_tool_tests() -> None:
    workflow = _CONFORMANCE_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count('- ".github/workflows/wiki.yml"') == 2


def test_wiki_workflow_verifies_the_published_tree_after_push() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    publish = workflow.index("name: Publish wiki")
    verify = workflow.index("name: Verify published wiki")
    assert publish < verify
    assert "python -m scripts.docs.push_wiki --check-published" in workflow
