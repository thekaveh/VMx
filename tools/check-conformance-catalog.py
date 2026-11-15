#!/usr/bin/env python3
"""Structure check for the conformance catalog and the chapter Conformance tables.

`tools/check-conformance-coverage.py` checks test markers. No other tool reads the
chapter Conformance tables or the Given/When/Then shape of the catalog entries.
This check reads both and reports each break of the catalog rules:

- a library ID in no chapter Conformance table, or a table ID not in the catalog;
- a `§N` cited in a table row that names no heading of its chapter (a reference
  written as `chapter NN §N` names another chapter and is not checked);
- a "Chapter 12 §N holds the `X` IDs" sentence whose section holds no `X` ID, or
  a range that names an ID absent from its section;
- a `###` line from §3 onward that is not `### ` plus exactly one ID of a §1 prefix;
- an entry without **Given**, without **Then**, or without a **When** clause. The
  setup-only marker `**When** (setup only)` counts as a **When** clause.

Exit codes:
    0  No structure problem.
    1  At least one structure problem; each is printed as `path:line: message`.
    2  The catalog or a chapter cannot be read, or the catalog has no §1 prefix table.

Usage:
    python3 tools/check-conformance-catalog.py [--repo-root PATH]
"""

import argparse
import bisect
import importlib.util
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


def _load_coverage_module():  # type: ignore[no-untyped-def]
    # Reuse the coverage tool's ID pattern, scenario prefixes and catalog parser.
    name = "check_conformance_coverage"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / "check-conformance-coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ccc = _load_coverage_module()

CATALOG_REL = Path("spec/12-conformance.md")
# Chapter 00 has no Conformance section, and chapter 12 is the catalog itself.
_UNLISTED_CHAPTERS = frozenset({"00", "12"})
# Catalog sections from this one on hold entries; §1 and §2 hold the prefix
# table and the notation rules.
_FIRST_ENTRY_SECTION = 3
SETUP_ONLY_WHEN = "**When** (setup only)"

_SECTION_HEADING = re.compile(r"^## (\d+)\. ")
_CONFORMANCE_HEADING = re.compile(r"^## \d+\. Conformance\s*$")
_NUMBERED_HEADING = re.compile(r"^#{2,4} (\d+(?:\.\d+)*)\.? ")
_PREFIX_ROW = re.compile(r"^\|\s*`([A-Z]{3,5})-NNN`")
_TABLE_ID = re.compile(r"`([A-Z]{3,5})-(\d{3})`(?:\s*\.\.\s*`([A-Z]{3,5})-(\d{3})`)?")
_TABLE_REF = re.compile(r"§(\d+(?:\.\d+)*)")
_CHAPTER_REF_BEFORE = re.compile(r"chapter \d+ $", re.IGNORECASE)
_CATALOG_SENTENCE = re.compile(r"Chapter 12 (§[^.]*)\.")
_CLAUSE_SPLIT = re.compile(r",\s*(?:and\s+)?")
_CLAUSE_SECTION = re.compile(r"§(\d+)")
_CLAUSE_PREFIX = re.compile(r"`([A-Z]{3,5})(?:-\d{3})?`")
_CLAUSE_RANGE = re.compile(r"`([A-Z]{3,5})-(\d{3})` to `([A-Z]{3,5})-(\d{3})`")
_GIVEN = "**Given**"
_THEN = "**Then**"
_WHEN = "**When**"


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class Catalog:
    lines: list[str]
    prefixes: frozenset[str]
    all_ids: frozenset[str]
    heading_line: dict[str, int]
    ids_by_section: dict[int, frozenset[str]]

    def section_prefixes(self, section: int) -> set[str]:
        return {_prefix(i) for i in self.ids_by_section.get(section, frozenset())}


def _prefix(catalog_id: str) -> str:
    return catalog_id.split("-", 1)[0]


def _id_text(match: re.Match[str]) -> str:
    return f"{match.group(1)}-{match.group(2)}"


def _scan_catalog(lines: list[str]) -> Catalog:
    prefixes: set[str] = set()
    all_ids: set[str] = set()
    heading_line: dict[str, int] = {}
    ids_by_section: dict[int, set[str]] = defaultdict(set)
    section: int | None = None
    in_prefix_table = False
    for number, text in enumerate(lines, start=1):
        section_match = _SECTION_HEADING.match(text)
        if section_match:
            section = int(section_match.group(1))
            in_prefix_table = section == 1
            continue
        if in_prefix_table:
            prefix_match = _PREFIX_ROW.match(text)
            if prefix_match:
                prefixes.add(prefix_match.group(1))
        if not text.startswith("### "):
            continue
        for match in ccc._ID_PATTERN.finditer(text):
            catalog_id = _id_text(match)
            all_ids.add(catalog_id)
            heading_line.setdefault(catalog_id, number)
            if section is not None:
                ids_by_section[section].add(catalog_id)
    return Catalog(
        lines=lines,
        prefixes=frozenset(prefixes),
        all_ids=frozenset(all_ids),
        heading_line=heading_line,
        ids_by_section={s: frozenset(ids) for s, ids in ids_by_section.items()},
    )


def _conformance_section(lines: list[str]) -> list[tuple[int, str]] | None:
    """Return (line number, text) for each line of the chapter's Conformance section."""
    start: int | None = None
    for index, text in enumerate(lines):
        if start is None:
            if _CONFORMANCE_HEADING.match(text):
                start = index + 1
        elif text.startswith("## "):
            return [(i + 1, lines[i]) for i in range(start, index)]
    if start is None:
        return None
    return [(i + 1, lines[i]) for i in range(start, len(lines))]


def _numbered_headings(lines: list[str]) -> set[str]:
    numbers: set[str] = set()
    for text in lines:
        match = _NUMBERED_HEADING.match(text)
        if match:
            numbers.add(match.group(1))
    return numbers


def _table_ids(first_cell: str) -> tuple[list[str], str | None]:
    """Return the IDs named by an IDs cell, or an error for a malformed range."""
    ids: list[str] = []
    for match in _TABLE_ID.finditer(first_cell):
        if match.group(3) is None:
            ids.append(_id_text(match))
            continue
        start, end = int(match.group(2)), int(match.group(4))
        if match.group(1) != match.group(3) or end < start:
            return ids, f"malformed ID range {match.group(0)}"
        ids.extend(f"{match.group(1)}-{n:03d}" for n in range(start, end + 1))
    return ids, None


def _check_table_row(
    rel: str,
    number: int,
    text: str,
    headings: set[str],
    catalog: Catalog,
    covered: set[str],
) -> list[Problem]:
    problems: list[Problem] = []
    cells = text.split("|")
    first_cell = cells[1] if len(cells) > 1 else ""
    ids, range_error = _table_ids(first_cell)
    if range_error is not None:
        problems.append(Problem(rel, number, range_error))
    for catalog_id in ids:
        covered.add(catalog_id)
        if catalog_id not in catalog.all_ids:
            problems.append(Problem(rel, number, f"table ID {catalog_id} is not in the catalog"))
    for ref in _TABLE_REF.finditer(text):
        if _CHAPTER_REF_BEFORE.search(text[: ref.start()]):
            continue
        if ref.group(1) not in headings:
            problems.append(
                Problem(rel, number, f"§{ref.group(1)} names no heading of this chapter")
            )
    return problems


def _check_clause(rel: str, number: int, clause: str, catalog: Catalog) -> list[Problem]:
    sections = [int(s) for s in _CLAUSE_SECTION.findall(clause)]
    prefixes = sorted(set(_CLAUSE_PREFIX.findall(clause)))
    if not sections or not prefixes:
        return [
            Problem(
                rel,
                number,
                f"catalog sentence clause {clause.strip()!r} names no section or no ID prefix",
            )
        ]
    names = "/".join(prefixes)
    where = ", ".join(f"§{section}" for section in sections)
    problems: list[Problem] = []
    for section in sections:
        if not catalog.section_prefixes(section) & set(prefixes):
            problems.append(Problem(rel, number, f"catalog §{section} holds no {names} ID"))
    held_anywhere: set[str] = set()
    for section in sections:
        held_anywhere |= catalog.section_prefixes(section)
    for prefix in prefixes:
        if prefix not in held_anywhere:
            problems.append(
                Problem(
                    rel,
                    number,
                    f"no {prefix} ID in catalog {where}",
                )
            )
    range_match = _CLAUSE_RANGE.search(clause)
    if range_match is not None:
        start, end = int(range_match.group(2)), int(range_match.group(4))
        if range_match.group(1) != range_match.group(3) or end < start:
            problems.append(Problem(rel, number, f"malformed ID range {range_match.group(0)}"))
        else:
            for n in range(start, end + 1):
                catalog_id = f"{range_match.group(1)}-{n:03d}"
                if not any(
                    catalog_id in catalog.ids_by_section.get(section, frozenset())
                    for section in sections
                ):
                    problems.append(
                        Problem(
                            rel,
                            number,
                            f"{catalog_id} is not a heading of catalog {where}",
                        )
                    )
    return problems


def _check_sentences(rel: str, section: list[tuple[int, str]], catalog: Catalog) -> list[Problem]:
    """Check each "Chapter 12 §N ..." sentence, which may wrap across lines."""
    joined_parts: list[str] = []
    starts: list[int] = []
    numbers: list[int] = []
    offset = 0
    for number, text in section:
        if text.startswith("|"):
            continue
        starts.append(offset)
        numbers.append(number)
        joined_parts.append(text + " ")
        offset += len(text) + 1
    joined = "".join(joined_parts)
    problems: list[Problem] = []
    for match in _CATALOG_SENTENCE.finditer(joined):
        line_no = numbers[bisect.bisect_right(starts, match.start()) - 1]
        for clause in _CLAUSE_SPLIT.split(match.group(1)):
            problems.extend(_check_clause(rel, line_no, clause, catalog))
    return problems


def _check_chapter(
    rel: str,
    lines: list[str],
    catalog: Catalog,
    covered: set[str],
) -> list[Problem]:
    section = _conformance_section(lines)
    if section is None:
        return [Problem(rel, 1, "no `## N. Conformance` section")]
    headings = _numbered_headings(lines)
    problems: list[Problem] = []
    for number, text in section:
        if text.startswith("|"):
            problems.extend(_check_table_row(rel, number, text, headings, catalog, covered))
    problems.extend(_check_sentences(rel, section, catalog))
    return problems


def _has_when(text: str) -> bool:
    return text.startswith(_WHEN) and text[len(_WHEN) :].strip() != ""


def _entry_body(lines: list[str], heading_index: int) -> list[str]:
    body: list[str] = []
    for text in lines[heading_index + 1 :]:
        if text.startswith("#"):
            break
        body.append(text)
    return body


def _check_entry(rel: str, number: int, catalog_id: str, body: list[str]) -> list[Problem]:
    problems: list[Problem] = []
    if not any(text.startswith(_GIVEN) for text in body):
        problems.append(Problem(rel, number, f"{catalog_id} has no {_GIVEN} clause"))
    if not any(text.startswith(_THEN) for text in body):
        problems.append(Problem(rel, number, f"{catalog_id} has no {_THEN} clause"))
    if not any(_has_when(text) for text in body):
        problems.append(
            Problem(
                rel,
                number,
                f"{catalog_id} has no {_WHEN} clause and no setup-only marker `{SETUP_ONLY_WHEN}`",
            )
        )
    return problems


def _check_entries(rel: str, catalog: Catalog) -> list[Problem]:
    """Check each §3-and-later `###` line and the entry under it."""
    problems: list[Problem] = []
    section: int | None = None
    for index, text in enumerate(catalog.lines):
        section_match = _SECTION_HEADING.match(text)
        if section_match:
            section = int(section_match.group(1))
            continue
        if section is None or section < _FIRST_ENTRY_SECTION or not text.startswith("###"):
            continue
        number = index + 1
        matches = list(ccc._ID_PATTERN.finditer(text))
        well_formed = text.startswith("### ") and len(matches) == 1 and matches[0].start() == 4
        if not well_formed:
            problems.append(
                Problem(
                    rel,
                    number,
                    f"malformed heading {text!r}: expected '### ' then exactly one ID",
                )
            )
            continue
        catalog_id = _id_text(matches[0])
        prefix = matches[0].group(1)
        if prefix not in catalog.prefixes:
            problems.append(
                Problem(rel, number, f"{catalog_id} prefix {prefix} is not in the §1 table")
            )
        problems.extend(_check_entry(rel, number, catalog_id, _entry_body(catalog.lines, index)))
    return problems


def _sorted(problems: Iterable[Problem]) -> list[Problem]:
    return sorted(problems, key=lambda p: (p.path, p.line, p.message))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: the parent of this script).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root).resolve()
    catalog_path = repo_root / CATALOG_REL
    try:
        catalog_lines = catalog_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read catalog {catalog_path}: {exc}", file=sys.stderr)
        return 2
    catalog = _scan_catalog(catalog_lines)
    if not catalog.prefixes:
        print(f"ERROR: no ID prefix table in {catalog_path} section 1", file=sys.stderr)
        return 2
    library_ids = ccc.parse_catalog_ids(catalog_path)

    chapters = sorted(
        path
        for path in (repo_root / "spec").glob("[0-9][0-9]-*.md")
        if path.name[:2] not in _UNLISTED_CHAPTERS
    )
    covered: set[str] = set()
    problems: list[Problem] = []
    for chapter in chapters:
        rel = chapter.relative_to(repo_root).as_posix()
        try:
            lines = chapter.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"ERROR: cannot read chapter {chapter}: {exc}", file=sys.stderr)
            return 2
        problems.extend(_check_chapter(rel, lines, catalog, covered))

    catalog_rel = CATALOG_REL.as_posix()
    for catalog_id in sorted(library_ids - covered):
        problems.append(
            Problem(
                catalog_rel,
                catalog.heading_line[catalog_id],
                f"{catalog_id} is in no chapter Conformance table",
            )
        )
    problems.extend(_check_entries(catalog_rel, catalog))

    if problems:
        for problem in _sorted(problems):
            print(problem.render())
        print(file=sys.stderr)
        print(
            f"FAIL: {len(problems)} conformance catalog structure problem(s)",
            file=sys.stderr,
        )
        return 1
    print(
        f"Conformance catalog structure: {len(library_ids)} library IDs, "
        f"{len(chapters)} chapters, no problem found."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
