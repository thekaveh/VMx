"""Every conformance ID that spec/HISTORY.md names is a catalog heading (#1814).

The prefix table in ``spec/12-conformance.md`` section 1 defines the ID
families. A HISTORY line names one ID, or a range such as ``NOTIF-011..016``,
and each named ID must be a ``### ID`` heading in the catalog. HISTORY is not
edited by this check: a retired or renamed ID is an owner finding.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "spec"

# An ID or a range PREFIX-NNN..NNN, not preceded by a letter, digit or hyphen.
_ID_RE = re.compile(r"(?<![A-Za-z0-9-])([A-Z]+)-(\d{3})(?:\.\.(\d{3}))?(?!\d)")
_PREFIX_ROW_RE = re.compile(r"^\| `([A-Z]+)-NNN`", re.MULTILINE)
_HEADING_RE = re.compile(r"^### ([A-Z]+-\d{3})\b", re.MULTILINE)


def history_id_issues(spec_dir: Path) -> list[str]:
    """Return one line per HISTORY ID that the catalog has no heading for."""
    catalog = (spec_dir / "12-conformance.md").read_text(encoding="utf-8")
    prefixes = set(_PREFIX_ROW_RE.findall(catalog))
    headings = set(_HEADING_RE.findall(catalog))
    issues: list[str] = []
    history = (spec_dir / "HISTORY.md").read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(history, start=1):
        for match in _ID_RE.finditer(line):
            prefix, first = match.group(1), int(match.group(2))
            if prefix not in prefixes:
                continue  # a tag such as VMX-011 that the catalog does not define
            last = int(match.group(3) or first)
            for value in range(first, last + 1):
                cited = f"{prefix}-{value:03d}"
                if cited not in headings:
                    issues.append(
                        f"HISTORY.md:{number}: {cited} has no heading in 12-conformance.md"
                    )
    return issues


def test_history_names_only_catalog_headings() -> None:
    assert history_id_issues(SPEC) == []


_CATALOG = (
    "# 12 — Conformance test catalog\n\n## 1. Identifier prefixes\n\n"
    "| Prefix | Area |\n| --- | --- |\n| `LIFE-NNN` | Lifecycle |\n| `THEME-NNN` | Theme |\n\n"
    "## 3. Lifecycle\n\n### LIFE-001 — construct\n\n### LIFE-002 — destruct\n\n"
    "### THEME-001 — one\n\n### THEME-002 — two\n\n### THEME-003 — three\n\n"
    "### THEME-005 — five\n"
)
_HISTORY = (
    "# History\n\n## 1. v1.1.0 changes\n\n"
    "- Adds `LIFE-002` and `LIFE-009` (ADR-0001).\n\n"
    "## 2. v1.2.0 changes\n\n"
    "- Adds `THEME-001..005`; `VMX-011` is a process tag, not a catalog ID.\n"
)


def test_history_id_check_reports_ids_missing_from_the_catalog(tmp_path: Path) -> None:
    (tmp_path / "12-conformance.md").write_text(_CATALOG, encoding="utf-8")
    (tmp_path / "HISTORY.md").write_text(_HISTORY, encoding="utf-8")
    assert history_id_issues(tmp_path) == [
        "HISTORY.md:5: LIFE-009 has no heading in 12-conformance.md",
        "HISTORY.md:9: THEME-004 has no heading in 12-conformance.md",
    ]


def test_history_id_check_passes_when_every_named_id_is_a_heading(tmp_path: Path) -> None:
    (tmp_path / "12-conformance.md").write_text(_CATALOG, encoding="utf-8")
    (tmp_path / "HISTORY.md").write_text(
        "# History\n\n## 1. v1.1.0 changes\n\n- Adds `LIFE-002` and `THEME-001..003`.\n",
        encoding="utf-8",
    )
    assert history_id_issues(tmp_path) == []
