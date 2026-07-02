from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = REPO_ROOT / "docs" / "site"
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


def test_language_specific_site_code_fences_are_tabbed() -> None:
    offenders: list[str] = []
    for path in sorted(DOCS_SITE.rglob("*.md")):
        for line in language_fences_outside_tabs(path):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")

    assert offenders == []
