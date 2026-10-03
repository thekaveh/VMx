"""Contract checks for documentation workflow change detection."""

import fnmatch
import re
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "docs.yml"
_WIKI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "wiki.yml"


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
        assert workflow.count(f'- "{path}"') == 1, f"{path} must trigger docs validation on push"

    pull_request = workflow.split("  pull_request:\n", maxsplit=1)[1].split(
        "  workflow_dispatch:", maxsplit=1
    )[0]
    assert "    paths:" not in pull_request
    assert 'name: "required: docs"' in workflow


def test_opener_contract_and_poster_trigger_every_publication_workflow() -> None:
    for workflow_path in (_WORKFLOW, _WIKI_WORKFLOW):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert workflow.count('- "docs/opener.yaml"') == 1
        assert workflow.count('- "assets/vmx-poster.png"') == 1


def test_docs_workflow_watches_every_checked_snippet_source() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    push = workflow.split("  pull_request:\n", maxsplit=1)[0]
    patterns = re.findall(r'^      - "([^"]+)"$', push, re.M)
    markdown = [
        *(_REPO_ROOT / "docs" / "content").rglob("*.md"),
        *(_REPO_ROOT / "packages").glob("*/README.md"),
    ]
    sources = {
        source
        for page in markdown
        for source in re.findall(
            r"^<!-- checked-snippet: ([^#\s]+)(?:#[\w-]+)? -->$",
            page.read_text(encoding="utf-8"),
            re.M,
        )
    }
    assert sources, "no checked-snippet markers found"
    unwatched = sorted(
        source
        for source in sources
        if not any(fnmatch.fnmatch(source, pattern) for pattern in patterns)
    )
    assert unwatched == [], f"docs.yml push paths miss checked sources: {unwatched}"


def _docs_concurrency_group(event_name: str, ref: str) -> str:
    """Evaluate docs.yml's workflow-level concurrency group for one run."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    block = re.search(r"^concurrency:\n((?:  .*\n)+)", workflow, re.M)
    assert block, "docs.yml must declare workflow-level concurrency"
    assert re.search(r"^  cancel-in-progress: false$", block.group(1), re.M)
    group = re.search(r"^  group: (.+)$", block.group(1), re.M)
    assert group, "docs.yml concurrency must name a group"
    value = group.group(1).strip()
    expression = re.fullmatch(r"\$\{\{(.+)\}\}", value)
    if expression is None:
        return value
    python = expression.group(1).replace("&&", " and ").replace("||", " or ")
    context = {
        "github": SimpleNamespace(event_name=event_name, ref=ref),
        "format": lambda template, *args: template.format(*args),
    }
    return str(eval(python, {"__builtins__": {}}, context))


def test_only_the_main_publication_shares_the_pages_concurrency_group() -> None:
    # A group holds one running and one pending run, and a newly queued run
    # cancels the pending one. Unrelated pull requests and develop pushes must
    # never displace each other or a pending main publication (#534).
    first_pr = _docs_concurrency_group("pull_request", "refs/pull/1/merge")
    second_pr = _docs_concurrency_group("pull_request", "refs/pull/2/merge")
    develop = _docs_concurrency_group("push", "refs/heads/develop")
    main = _docs_concurrency_group("push", "refs/heads/main")

    assert main == "pages"
    assert _docs_concurrency_group("workflow_dispatch", "refs/heads/main") == "pages"
    assert len({first_pr, second_pr, develop, main}) == 4
    assert _docs_concurrency_group("pull_request", "refs/pull/1/merge") == first_pr
