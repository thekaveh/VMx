from __future__ import annotations

from pathlib import Path

import pytest
from scripts.docs.check_docs import check_checked_snippets

ROOT = Path(__file__).resolve().parents[2]

SOURCE = """\
def helper():
    return 1

def recipe():
    # docs-snippet:start demo
    value = helper()
    print(value)
    # docs-snippet:end demo
"""


def _page(root: Path, body: str, relative: str = "docs/content/guide.md") -> Path:
    page = root / relative
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    return page


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/recipe.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_a_region_fence_equal_to_its_source_passes(repo: Path) -> None:
    _page(
        repo,
        "# Guide\n\n<!-- checked-snippet: src/recipe.py#demo -->\n\n"
        "```python\nvalue = helper()\nprint(value)\n```\n",
    )

    assert check_checked_snippets(repo) == []


def test_a_whole_file_fence_equal_to_its_source_passes(repo: Path) -> None:
    _page(repo, f"<!-- checked-snippet: src/recipe.py -->\n```python\n{SOURCE}```\n")

    assert check_checked_snippets(repo) == []


def test_a_drifted_fence_is_reported(repo: Path) -> None:
    _page(
        repo,
        "<!-- checked-snippet: src/recipe.py#demo -->\n"
        "```python\nvalue = helpr()\nprint(value)\n```\n",
    )

    findings = check_checked_snippets(repo)

    assert len(findings) == 1
    assert "guide.md:1: fence differs from checked source src/recipe.py#demo" in findings[0].message


@pytest.mark.parametrize(
    ("marker", "problem"),
    [
        ("src/missing.py", "source src/missing.py does not exist"),
        ("src/recipe.py#absent", "needs exactly one docs-snippet:start/end pair for 'absent'"),
    ],
)
def test_unresolvable_sources_are_reported(repo: Path, marker: str, problem: str) -> None:
    _page(repo, f"<!-- checked-snippet: {marker} -->\n```python\nx\n```\n")

    findings = check_checked_snippets(repo)

    assert len(findings) == 1 and problem in findings[0].message


def test_a_marker_without_a_fence_is_reported(repo: Path) -> None:
    _page(repo, "<!-- checked-snippet: src/recipe.py#demo -->\n\nProse, not code.\n")

    findings = check_checked_snippets(repo)

    assert len(findings) == 1 and "checked snippet has no fence" in findings[0].message


def test_a_stale_generated_copy_is_reported(repo: Path) -> None:
    good = (
        "<!-- checked-snippet: src/recipe.py#demo -->\n"
        "```python\nvalue = helper()\nprint(value)\n```\n"
    )
    _page(repo, good)
    _page(repo, good.replace("print(value)", "print(old)"), "generated/wiki/Guide.md")

    findings = check_checked_snippets(repo)

    assert [f.message.split(":")[0].endswith("Guide.md") for f in findings] == [True]


def test_the_repository_snippets_match_their_sources() -> None:
    assert check_checked_snippets(ROOT) == []
