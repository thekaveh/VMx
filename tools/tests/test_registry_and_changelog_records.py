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

import pytest

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


# ADR preamble fields and back-links (#1810). Registry section 2 of
# spec/ADRs/README.md defines the field names and back-link verbs that ADRs use.

_PREAMBLE_FIELD_RE = re.compile(r"^(?:- )?\*\*([A-Za-z][A-Za-z\- ]*[A-Za-z]):\*\*", re.MULTILINE)
_BACK_LINK_VERB_RE = re.compile(r"\b([a-z]+) by\s+\[?adr-\d{4}")
_RELATIONSHIP_VERBS = {
    "Supersedes": "superseded",
    "Amends": "amended",
    "Extends": "extended",
    "Clarifies": "clarified",
}

# Owner findings from #1814. This PR is a check, not an ADR edit, so each entry
# exempts one back-link that the real tree lacks: (earlier ADR, later ADR,
# surface) -> reason. A surface is "Status", "Status first word", "registry cell",
# "registry row" or "file", as back_link_gaps names it.
BACK_LINK_EXEMPTIONS: dict[tuple[str, str, str], str] = {
    ("0024", "0142", "Status"): (
        "ADR-0024 Status says 'adopted for ... by ADR-0142', not the 'amended by' back-link "
        "that section 2.3 defines. Owner finding: reword the Status back-link. The registry "
        "cell already says 'amended by 0142'."
    ),
    ("0151", "0213", "registry cell"): (
        "ADR-0213 Supersedes ADR-0151 Decision rule 3, and the ADR-0151 Status says 'superseded "
        "by ADR-0213'. The registry cell says 'amended by 0213'. Owner finding: the cell should "
        "repeat 'superseded by 0213'."
    ),
}


def _registry_section(registry_text: str, start: str, end: str) -> str:
    begin = registry_text.index(start)
    return registry_text[begin : registry_text.index(end, begin)]


def _defined_preamble_fields(registry_text: str) -> set[str]:
    """Names that registry sections 2.1 (preamble) and 2.2 (relationships) define."""
    preamble_format = _registry_section(registry_text, "### 2.1", "### 2.2")
    relationships = _registry_section(registry_text, "### 2.2", "### 2.3")
    fields = set(re.findall(r"\*\*([A-Za-z][A-Za-z ]*):\*\*", preamble_format))
    return fields | set(re.findall(r"`([A-Z][a-z]+)`", relationships))


def _defined_relationship_fields(registry_text: str) -> set[str]:
    """Return the relationship field names in the table of registry section 2.2."""
    section = _registry_section(registry_text, "### 2.2", "### 2.3")
    return set(re.findall(r"^\| `([A-Z][a-z]+)`\s*\|", section, re.MULTILINE))


_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")
_ADR_REF_RE = re.compile(r"ADR-(\d{4})")


def _preamble_field_values(preamble: str) -> list[tuple[str, str]]:
    """Return (field name, value text) for each bold field of an ADR preamble."""
    matches = list(_PREAMBLE_FIELD_RE.finditer(preamble))
    ends = [match.start() for match in matches[1:]] + [len(preamble)]
    return [
        (match.group(1), preamble[match.end() : end])
        for match, end in zip(matches, ends, strict=True)
    ]


def _relationship_edges(adr_dir: Path) -> list[tuple[str, str, str, bool]]:
    """Return (later, field, earlier, whole) for each ADR a relationship field names.

    A value ends at ``Related:``. ``whole`` is true when the value is only ADR
    links, so the earlier ADR is replaced as a whole decision (ADR-0052 names
    ADR-0033 this way). A value with a section or rule names a part instead.
    """
    edges: list[tuple[str, str, str, bool]] = []
    for path in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        later = path.name[:4]
        for field, value in _preamble_field_values(_preamble(path.read_text(encoding="utf-8"))):
            if field not in _RELATIONSHIP_VERBS:
                continue
            value = re.split(r"\bRelated:", value, maxsplit=1)[0]
            rest = _ADR_REF_RE.sub("", _LINK_RE.sub("", value))
            whole = not re.sub(r"\band\b|[\s,.;]", "", rest)
            edges.extend(
                (later, field, earlier, whole)
                for earlier in dict.fromkeys(_ADR_REF_RE.findall(value))
            )
    return edges


def back_link_gaps(adr_dir: Path) -> list[tuple[str, str, str]]:
    """Return (earlier, later, surface) for each back-link that a relationship field lacks.

    The earlier ADR's Status must read ``<verb> by ADR-NNNN`` and its registry
    cell must read ``<verb> by NNNN`` (section 2.3). A whole supersession also
    needs a Status that starts ``Superseded``. A surface is ``file`` or
    ``registry row`` when the earlier ADR is missing from the tree.
    """
    registry = registry_rows((adr_dir / "README.md").read_text(encoding="utf-8"))
    cells = {number: cell for number, _, cell in registry}
    gaps: list[tuple[str, str, str]] = []
    for later, field, earlier, whole in _relationship_edges(adr_dir):
        verb = _RELATIONSHIP_VERBS[field]
        path = next(adr_dir.glob(f"{earlier}-*.md"), None)
        if path is None:
            gaps.append((earlier, later, "file"))
            continue
        status = adr_status(path.read_text(encoding="utf-8"))
        if not re.search(rf"\b{verb} by\b[^;)]*ADR-{later}\b", status, re.IGNORECASE):
            gaps.append((earlier, later, "Status"))
        if whole and field == "Supersedes" and not re.match(r"Superseded\b", status):
            gaps.append((earlier, later, "Status first word"))
        if earlier not in cells:
            gaps.append((earlier, later, "registry row"))
        elif not re.search(rf"\b{verb} by\b[^;)]*\b{later}\b", cells[earlier], re.IGNORECASE):
            gaps.append((earlier, later, "registry cell"))
    return gaps


def _preamble(text: str) -> str:
    return re.split(r"^## ", text, maxsplit=1, flags=re.MULTILINE)[0]


def test_adr_preamble_fields_are_defined_by_registry_format() -> None:
    defined = _defined_preamble_fields(REGISTRY.read_text(encoding="utf-8"))
    assert {"Status", "Date", "Spec version", "Supersedes", "Amends", "Extends"} <= defined
    assert {"Clarifies", "Related"} <= defined
    undefined: dict[str, list[str]] = {}
    for path in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        fields = _PREAMBLE_FIELD_RE.findall(_preamble(path.read_text(encoding="utf-8")))
        if set(fields) - defined:
            undefined[path.name] = sorted(set(fields) - defined)
    assert undefined == {}


def test_status_back_link_verbs_are_defined_by_registry_format() -> None:
    verbs_text = _registry_section(REGISTRY.read_text(encoding="utf-8"), "### 2.3", "### 2.4")
    undefined: dict[str, list[str]] = {}
    for path in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        status = adr_status(path.read_text(encoding="utf-8")).lower()
        for verb in _BACK_LINK_VERB_RE.findall(status):
            if f"`{verb} by`" not in verbs_text.lower():
                undefined.setdefault(verb, []).append(path.name)
    assert undefined == {}


def test_relationship_fields_are_the_registry_fields() -> None:
    registry = REGISTRY.read_text(encoding="utf-8")
    assert set(_RELATIONSHIP_VERBS) == _defined_relationship_fields(registry)


def test_relationship_fields_have_back_links_in_status_and_registry() -> None:
    gaps = back_link_gaps(ADR_DIR)
    assert sorted(set(gaps) - set(BACK_LINK_EXEMPTIONS)) == []
    assert sorted(set(BACK_LINK_EXEMPTIONS) - set(gaps)) == []  # each exemption is still needed


def _adr_tree(root: Path, rows: tuple[tuple[str, str, str], ...], adrs: dict[str, str]) -> Path:
    """Write a small spec/ADRs tree: a registry with the given rows, and the ADR files."""
    adr_dir = root / "spec" / "ADRs"
    adr_dir.mkdir(parents=True)
    (adr_dir / "README.md").write_text(_registry(*rows), encoding="utf-8")
    for file_name, text in adrs.items():
        (adr_dir / file_name).write_text(text, encoding="utf-8")
    return adr_dir


_EARLIER_ACCEPTED = "# ADR 0001\n\n- **Status:** Accepted\n- **Date:** 2026-01-01\n"
_BOTH_ACCEPTED = (
    ("0001", "0001-a.md", "Accepted"),
    ("0002", "0002-b.md", "Accepted"),
)


def _later(field: str, value: str) -> str:
    return f"# ADR 0002\n\n- **Status:** Accepted\n- **Date:** 2026-01-02\n- **{field}:** {value}\n"


def test_back_link_check_reports_a_superseded_adr_without_a_back_link(tmp_path: Path) -> None:
    adr_dir = _adr_tree(
        tmp_path,
        _BOTH_ACCEPTED,
        {
            "0001-a.md": _EARLIER_ACCEPTED,
            "0002-b.md": _later("Supersedes", "[ADR-0001](0001-a.md)."),
        },
    )
    assert set(back_link_gaps(adr_dir)) == {
        ("0001", "0002", "Status"),
        ("0001", "0002", "Status first word"),
        ("0001", "0002", "registry cell"),
    }


def test_back_link_check_accepts_a_superseded_adr_with_back_links(tmp_path: Path) -> None:
    adr_dir = _adr_tree(
        tmp_path,
        (("0001", "0001-a.md", "Superseded by 0002"), ("0002", "0002-b.md", "Accepted")),
        {
            "0001-a.md": (
                "# ADR 0001\n\n- **Status:** Superseded by ADR-0002\n- **Date:** 2026-01-01\n"
            ),
            "0002-b.md": _later("Supersedes", "[ADR-0001](0001-a.md)."),
        },
    )
    assert back_link_gaps(adr_dir) == []


def test_back_link_check_accepts_a_partial_supersession_kept_accepted(tmp_path: Path) -> None:
    adr_dir = _adr_tree(
        tmp_path,
        (
            ("0001", "0001-a.md", "Accepted (§2 superseded by 0002)"),
            ("0002", "0002-b.md", "Accepted"),
        ),
        {
            "0001-a.md": (
                "# ADR 0001\n\n- **Status:** Accepted (§2 superseded by ADR-0002)\n"
                "- **Date:** 2026-01-01\n"
            ),
            "0002-b.md": _later("Supersedes", "[ADR-0001](0001-a.md) §2."),
        },
    )
    assert back_link_gaps(adr_dir) == []


@pytest.mark.parametrize("field", ["Amends", "Extends", "Clarifies"])
def test_back_link_check_reports_each_non_supersession_field(tmp_path: Path, field: str) -> None:
    adr_dir = _adr_tree(
        tmp_path,
        _BOTH_ACCEPTED,
        {"0001-a.md": _EARLIER_ACCEPTED, "0002-b.md": _later(field, "[ADR-0001](0001-a.md) §2.")},
    )
    gaps = set(back_link_gaps(adr_dir))
    assert ("0001", "0002", "Status") in gaps
    assert ("0001", "0002", "registry cell") in gaps


def test_back_link_check_requires_the_verb_of_the_field(tmp_path: Path) -> None:
    adr_dir = _adr_tree(
        tmp_path,
        (("0001", "0001-a.md", "Accepted (amended by 0002)"), ("0002", "0002-b.md", "Accepted")),
        {
            "0001-a.md": (
                "# ADR 0001\n\n- **Status:** Accepted (amended by ADR-0002)\n"
                "- **Date:** 2026-01-01\n"
            ),
            "0002-b.md": _later("Extends", "[ADR-0001](0001-a.md) §2."),
        },
    )
    gaps = set(back_link_gaps(adr_dir))
    assert ("0001", "0002", "Status") in gaps
    assert ("0001", "0002", "registry cell") in gaps
