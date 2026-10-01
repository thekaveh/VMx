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
        ("src/recipe.py#absent", "has no docs-snippet:start/end pair for 'absent'"),
    ],
)
def test_unresolvable_sources_are_reported(repo: Path, marker: str, problem: str) -> None:
    _page(repo, f"<!-- checked-snippet: {marker} -->\n```python\nx\n```\n")

    findings = check_checked_snippets(repo)

    assert len(findings) == 1 and problem in findings[0].message


def test_a_region_split_into_parts_is_joined_in_order(repo: Path) -> None:
    (repo / "src/adapter.cs").write_text(
        "// docs-snippet:start adapter\n"
        "using System;\n"
        "\n"
        "// docs-snippet:end adapter\n"
        "namespace Hidden;\n"
        "\n"
        "// docs-snippet:start adapter\n"
        "public sealed class Adapter { }\n"
        "// docs-snippet:end adapter\n",
        encoding="utf-8",
    )
    _page(
        repo,
        "<!-- checked-snippet: src/adapter.cs#adapter -->\n"
        "```csharp\nusing System;\n\npublic sealed class Adapter { }\n```\n",
    )

    assert check_checked_snippets(repo) == []


def test_a_region_name_matches_exactly(repo: Path) -> None:
    (repo / "src/two.py").write_text(
        "# docs-snippet:start demo-extended\nlonger = 2\n# docs-snippet:end demo-extended\n"
        "# docs-snippet:start demo\nshort = 1\n# docs-snippet:end demo\n",
        encoding="utf-8",
    )
    _page(repo, "<!-- checked-snippet: src/two.py#demo -->\n```python\nshort = 1\n```\n")

    assert check_checked_snippets(repo) == []


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        ("# docs-snippet:start demo\nx = 1\n", "never closes 'demo'"),
        ("x = 1\n# docs-snippet:end demo\n", "closes 'demo' before opening it"),
        (
            "# docs-snippet:start demo\n# docs-snippet:start demo\n# docs-snippet:end demo\n",
            "opens 'demo' again before closing it",
        ),
    ],
)
def test_unbalanced_region_markers_are_reported(repo: Path, source: str, problem: str) -> None:
    (repo / "src/bad.py").write_text(source, encoding="utf-8")
    _page(repo, "<!-- checked-snippet: src/bad.py#demo -->\n```python\nx = 1\n```\n")

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


def test_a_drifted_package_readme_copy_is_reported(repo: Path) -> None:
    _page(
        repo,
        "<!-- checked-snippet: src/recipe.py#demo -->\n"
        "```python\nvalue = helper()\nprint(stale)\n```\n",
        "packages/adapter/README.md",
    )

    findings = check_checked_snippets(repo)

    assert len(findings) == 1
    assert "packages/adapter/README.md:1: fence differs" in findings[0].message


def test_the_repository_snippets_match_their_sources() -> None:
    assert check_checked_snippets(ROOT) == []
