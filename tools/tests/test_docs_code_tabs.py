from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = REPO_ROOT / "generated" / "site"
LANGUAGE_FENCE_RE = re.compile(r"^\s*```(?:csharp|python|typescript|ts|swift|javascript|js)\b")
TAB_RE = re.compile(r'^=== "')
TAB_LOOKBACK_LINES = 4


def is_attached_to_tab(lines: list[str], fence_index: int) -> bool:
    start = max(0, fence_index - TAB_LOOKBACK_LINES)
    return any(TAB_RE.match(lines[index]) for index in range(start, fence_index))


def language_fences_outside_tabs(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    bad_lines: list[int] = []
    for index, line in enumerate(lines):
        if LANGUAGE_FENCE_RE.match(line) and not is_attached_to_tab(lines, index):
            bad_lines.append(index + 1)
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


def test_language_specific_site_code_fences_are_tabbed() -> None:
    if not DOCS_SITE.is_dir():
        pytest.skip("generated documentation site is not built (docs CI job / local docs build)")
    pages = sorted(DOCS_SITE.rglob("*.md"))
    assert len(pages) >= 60, "the generated-site scan must cover the complete manifest"
    tabbed_pages = [
        path
        for path in pages
        if any(TAB_RE.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    ]
    assert len(tabbed_pages) >= 10, "expected the multi-flavor pages to retain code tabs"


def test_site_tab_blocks_indent_their_content() -> None:
    if not DOCS_SITE.is_dir():
        pytest.skip("generated documentation site is not built (docs CI job / local docs build)")
    offenders: list[str] = []
    for path in sorted(DOCS_SITE.rglob("*.md")):
        for line in tab_markers_without_indented_content(path):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")

    assert offenders == []
