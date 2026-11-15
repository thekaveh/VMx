from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = REPO_ROOT / "generated" / "site"
TAB_RE = re.compile(r'^=== "')
FENCE_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
# The five flavors, plus javascript, which the site has always checked.
LANGUAGES = frozenset({"csharp", "python", "typescript", "swift", "javascript", "rust"})
LANGUAGE_ALIASES = {"ts": "typescript", "js": "javascript"}
SITE_MISSING = (
    "generated documentation site is not built (run python -m scripts.docs.build_docs --site)"
)


def _fence_language(info: str) -> str:
    words = info.split()
    word = words[0] if words else ""
    return LANGUAGE_ALIASES.get(word, word)


def _closes(line: str, marker: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(marker) and not stripped.strip(marker[0])


def language_fences_outside_tabs(path: Path) -> list[int]:
    """Return the 1-based line numbers of unindented language fences that break a code tab.

    A language fence opens with csharp, python, typescript (or ts), swift,
    javascript (or js) or rust. The rule has two parts:

    1. An indented fence is tab content and never fails. It can still be the
       previous fence for part 2.
    2. An unindented language fence fails when the previous fence on the page
       is a language fence of a different language, and only blank lines or
       HTML comments stand between the two fences.

    The second part matches the shape that mdformat leaves when it unindents
    tab content. A single language fence on its own, or one that follows prose
    or a non-language fence, is not reported. Fences inside another fence are
    content.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    bad_lines: list[int] = []
    # (marker, language) of the block being read.
    open_fence: tuple[str, str] | None = None
    # Language of the last fence while only blank lines or comments follow it.
    previous_language: str | None = None
    in_comment = False
    for number, line in enumerate(lines, start=1):
        if open_fence is not None:
            marker, language = open_fence
            if _closes(line, marker):
                previous_language = language
                open_fence = None
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        fence = FENCE_RE.match(line)
        if fence is not None:
            language = _fence_language(fence.group("info"))
            if (
                not fence.group("indent")
                and language in LANGUAGES
                and previous_language in LANGUAGES
                and previous_language != language
            ):
                bad_lines.append(number)
            open_fence = (fence.group("marker"), language)
            previous_language = None
            continue
        if not line.strip():
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        previous_language = None
    return bad_lines


def tab_markers_without_indented_content(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    bad_lines: list[int] = []
    for index, line in enumerate(lines):
        if not TAB_RE.match(line):
            continue
        content_index = index + 1
        while content_index < len(lines) and not lines[content_index]:
            content_index += 1
        if content_index == len(lines) or not lines[content_index].startswith("    "):
            bad_lines.append(index + 1)
    return bad_lines


def _require_site() -> None:
    if DOCS_SITE.is_dir():
        return
    # Mirrors tests/docs/test_new_adr_diagram_generation.py: CI builds the site
    # before this test runs, so a missing site there is a broken job, not a skip.
    if os.environ.get("CI"):
        pytest.fail(SITE_MISSING)
    pytest.skip(SITE_MISSING)


def test_language_specific_site_code_fences_are_tabbed() -> None:
    _require_site()
    pages = sorted(DOCS_SITE.rglob("*.md"))
    assert len(pages) >= 60, "the generated-site scan must cover the complete manifest"
    tabbed_pages = [
        path
        for path in pages
        if any(TAB_RE.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    ]
    assert len(tabbed_pages) >= 10, "expected the multi-flavor pages to retain code tabs"
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}"
        for path in pages
        for line in language_fences_outside_tabs(path)
    ]
    assert offenders == []


def test_site_tab_blocks_indent_their_content() -> None:
    _require_site()
    offenders: list[str] = []
    for path in sorted(DOCS_SITE.rglob("*.md")):
        for line in tab_markers_without_indented_content(path):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")

    assert offenders == []


def _page(tmp_path: Path, text: str) -> Path:
    page = tmp_path / "page.md"
    page.write_text(text, encoding="utf-8")
    return page


def test_unindented_fence_after_other_flavor_fence_is_reported(tmp_path: Path) -> None:
    page = _page(tmp_path, "# Example\n\n```csharp\nvar a = 1;\n```\n\n```python\na = 1\n```\n")

    assert language_fences_outside_tabs(page) == [7]


def test_rust_fence_after_python_fence_is_reported(tmp_path: Path) -> None:
    page = _page(tmp_path, "```python\na = 1\n```\n\n```rust\nlet a = 1;\n```\n")

    assert language_fences_outside_tabs(page) == [5]


def test_ts_fence_after_typescript_fence_is_the_same_language(tmp_path: Path) -> None:
    page = _page(tmp_path, "```typescript\nconst a = 1;\n```\n\n```ts\nconst b = 2;\n```\n")

    assert language_fences_outside_tabs(page) == []


def test_comment_between_two_fences_does_not_separate_them(tmp_path: Path) -> None:
    page = _page(tmp_path, "```csharp\na\n```\n\n<!-- note -->\n```python\nb\n```\n")

    assert language_fences_outside_tabs(page) == [6]


def test_prose_between_two_fences_separates_them(tmp_path: Path) -> None:
    page = _page(tmp_path, "```csharp\na\n```\n\nText.\n\n```python\nb\n```\n")

    assert language_fences_outside_tabs(page) == []


def test_fence_without_a_language_does_not_count_as_previous(tmp_path: Path) -> None:
    page = _page(tmp_path, "```csharp\na\n```\n\n```text\nb\n```\n\n```python\nc\n```\n")

    assert language_fences_outside_tabs(page) == []


def test_fence_inside_another_fence_is_content(tmp_path: Path) -> None:
    page = _page(tmp_path, "````markdown\n```csharp\na\n```\n```python\nb\n```\n````\n")

    assert language_fences_outside_tabs(page) == []


def test_indented_fences_in_one_tab_never_fail(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '=== "C#"\n\n    ```csharp\n    a\n    ```\n\n    ```python\n    b\n    ```\n\n'
        '=== "Python"\n\n    ```python\n    c\n    ```\n',
    )

    assert language_fences_outside_tabs(page) == []


def test_unindented_fence_after_indented_other_flavor_fence_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '=== "C#"\n\n    ```csharp\n    a\n    ```\n\n```python\nb\n```\n',
    )

    assert language_fences_outside_tabs(page) == [7]
