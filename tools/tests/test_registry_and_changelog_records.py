"""Keep the ADR registry and the CHANGELOG sections free of merge drift (#1479).

Stacked-branch merges have repeated registry rows and CHANGELOG entries, put
registry rows out of number order, and left registry Status cells behind the
Status lines of the ADR files. These checks read the registry table in
``spec/ADRs/README.md`` and every bracketed CHANGELOG section.
"""

from __future__ import annotations

import re
from collections import Counter
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "spec" / "ADRs"
REGISTRY = ADR_DIR / "README.md"
CHANGELOGS = (
    *sorted((ROOT / "langs").glob("*/CHANGELOG.md")),
    ROOT / "packages/react/CHANGELOG.md",
)

_REGISTRY_ROW_RE = re.compile(r"^\| \[(\d{4})\]\(([^)]+)\)\s*\|")
_STATUS_LINE_RE = re.compile(r"^(?:- )?\*\*Status:\*\*\s*(.*)$")
_ADR_REFERENCE_RE = re.compile(r"\bADR-(\d{4})\b")
_FIRST_WORD_RE = re.compile(r"[A-Za-z]+")


def registry_rows(text: str) -> list[tuple[str, str, str]]:
    """Return (number, file, Status cell) for each registry index row."""
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = _REGISTRY_ROW_RE.match(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append((match.group(1), match.group(2), cells[-1]))
    return rows


def adr_status(text: str) -> str:
    """Return an ADR's Status value with its indented continuation lines."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _STATUS_LINE_RE.match(line)
        if match is None:
            continue
        parts = [match.group(1).strip()]
        for continuation in lines[index + 1 :]:
            if not continuation.strip() or not continuation[0].isspace():
                break
            parts.append(continuation.strip())
        return " ".join(parts)
    return ""


def registry_issues(registry_text: str, adr_texts: dict[str, str]) -> list[str]:
    """Report repeated, unordered or stale registry rows."""
    rows = registry_rows(registry_text)
    issues: list[str] = []
    counts = Counter(number for number, _, _ in rows)
    issues.extend(
        f"ADR-{number}: {count} registry rows" for number, count in counts.items() if count > 1
    )
    numbers = [int(number) for number, _, _ in rows]
    issues.extend(
        f"ADR-{current:04d} row follows ADR-{previous:04d}"
        for previous, current in pairwise(numbers)
        if current <= previous
    )
    for number, file_name, cell in rows:
        text = adr_texts.get(file_name)
        if text is None:
            issues.append(f"ADR-{number}: registry links missing file {file_name}")
            continue
        status = adr_status(text)
        if not status:
            issues.append(f"ADR-{number}: {file_name} has no Status line")
            continue
        status_word = _FIRST_WORD_RE.match(status)
        cell_word = _FIRST_WORD_RE.match(cell)
        if status_word is None or cell_word is None or status_word.group() != cell_word.group():
            issues.append(f"ADR-{number}: Status cell {cell!r} does not start like {status!r}")
        issues.extend(
            f"ADR-{number}: Status cell {cell!r} omits {reference}"
            for reference in dict.fromkeys(_ADR_REFERENCE_RE.findall(status))
            if not re.search(rf"\b{reference}\b", cell)
        )
    return issues


def _changelog_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split a CHANGELOG into its bracketed H2 sections."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## ["):
            sections.append((line, []))
        elif line.startswith("## "):
            sections.append(("", []))
        elif sections:
            sections[-1][1].append(line)
    return [(heading, body) for heading, body in sections if heading]


def _list_entries(body: list[str]) -> list[str]:
    """Return each complete top-level list entry, whitespace-normalized."""
    entries: list[list[str]] = []
    current: list[str] | None = None
    for line in body:
        if line.startswith(("- ", "* ")):
            current = [line[2:]]
            entries.append(current)
        elif current is not None and (not line.strip() or line[0].isspace()):
            current.append(line)
        else:
            current = None
    return [" ".join(" ".join(entry).split()) for entry in entries]


def changelog_issues(text: str) -> list[str]:
    """Report a complete list entry repeated inside one bracketed section."""
    issues: list[str] = []
    for heading, body in _changelog_sections(text):
        counts = Counter(_list_entries(body))
        issues.extend(
            f"{heading}: entry repeated {count} times: {entry[:80]!r}"
            for entry, count in counts.items()
            if count > 1
        )
    return issues


def _adr_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")
    }


def test_registry_rows_are_unique_ordered_and_current() -> None:
    adr_texts = _adr_texts()
    registry_text = REGISTRY.read_text(encoding="utf-8")
    assert registry_issues(registry_text, adr_texts) == []
    assert sorted(file_name for _, file_name, _ in registry_rows(registry_text)) == sorted(
        adr_texts
    )


def test_changelog_sections_have_no_repeated_entries() -> None:
    assert CHANGELOGS
    for changelog in CHANGELOGS:
        assert changelog_issues(changelog.read_text(encoding="utf-8")) == [], changelog


_FIXTURE_ADRS = {
    "0001-a.md": "# ADR 0001\n\n- **Status:** Accepted\n- **Date:** 2026-01-01\n",
    "0002-b.md": (
        "# ADR 0002\n\n- **Status:** Accepted (2026-01-02; amended by ADR-0003 and\n"
        "  ADR-0004)\n- **Date:** 2026-01-02\n"
    ),
    "0003-c.md": "# ADR 0003\n\n**Status:** Superseded by 0004\n",
}


def _registry(*rows: tuple[str, str, str]) -> str:
    header = "| # | Title | Spec version | Status |\n| - | - | - | - |\n"
    body = "".join(
        f"| [{number}]({file_name}) | Title | 3.0.0 | {cell} |\n"
        for number, file_name, cell in rows
    )
    return header + body


_GOOD_ROWS = (
    ("0001", "0001-a.md", "Accepted"),
    ("0002", "0002-b.md", "Accepted (amended by 0003 and 0004)"),
    ("0003", "0003-c.md", "Superseded by 0004"),
)


def test_registry_fixture_passes() -> None:
    assert registry_issues(_registry(*_GOOD_ROWS), _FIXTURE_ADRS) == []


def test_registry_rejects_repeated_row() -> None:
    issues = registry_issues(_registry(*_GOOD_ROWS, _GOOD_ROWS[2]), _FIXTURE_ADRS)
    assert "ADR-0003: 2 registry rows" in issues


def test_registry_rejects_rows_out_of_number_order() -> None:
    rows = (_GOOD_ROWS[0], _GOOD_ROWS[2], _GOOD_ROWS[1])
    assert "ADR-0002 row follows ADR-0003" in registry_issues(_registry(*rows), _FIXTURE_ADRS)


def test_registry_rejects_status_cell_with_another_first_word() -> None:
    rows = (_GOOD_ROWS[0], _GOOD_ROWS[1], ("0003", "0003-c.md", "Accepted"))
    issues = registry_issues(_registry(*rows), _FIXTURE_ADRS)
    assert issues == ["ADR-0003: Status cell 'Accepted' does not start like 'Superseded by 0004'"]


def test_registry_rejects_status_cell_missing_a_continuation_reference() -> None:
    rows = (_GOOD_ROWS[0], ("0002", "0002-b.md", "Accepted (amended by 0003)"), _GOOD_ROWS[2])
    issues = registry_issues(_registry(*rows), _FIXTURE_ADRS)
    assert issues == ["ADR-0002: Status cell 'Accepted (amended by 0003)' omits 0004"]


def test_registry_does_not_read_a_date_as_a_reference() -> None:
    adrs = {"0001-a.md": "- **Status:** Accepted (2026-10-25)\n"}
    rows = (("0001", "0001-a.md", "Accepted"),)
    assert registry_issues(_registry(*rows), adrs) == []


def test_changelog_rejects_a_repeated_complete_entry() -> None:
    text = (
        "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] — unreleased source version\n\n"
        "### Fixed\n\n- One fix that wraps\n  onto a second line.\n\n### Changed\n\n"
        "- One fix that wraps onto\n  a second line.\n\n## [1.0.0] — 2026-01-01\n\n"
        "- One fix that wraps onto a second line.\n"
    )
    issues = changelog_issues(text)
    assert len(issues) == 1
    assert issues[0].startswith("## [1.1.0] — unreleased source version: entry repeated 2 times")


def test_changelog_accepts_entries_that_share_only_a_first_line() -> None:
    text = (
        "## [Unreleased]\n\n## [1.0.0] — 2026-01-01\n\n- Shared first line,\n  then one ending.\n"
        "- Shared first line,\n  then another ending.\n"
    )
    assert changelog_issues(text) == []
