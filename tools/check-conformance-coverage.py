#!/usr/bin/env python3
"""Cross-language conformance coverage check.

Parses spec/12-conformance.md for every `XXX-NNN` conformance ID, then walks
langs/<lang>/tests/conformance/ for each active language and verifies every ID has
a matching test. Reports gaps to stdout and returns a non-zero exit code if any
language passed via --require has gaps.

Usage:
    python3 tools/check-conformance-coverage.py [--repo-root PATH] [--require LANG ...]

Examples:
    # Default: parse and report, never fail
    python3 tools/check-conformance-coverage.py

    # Require python and csharp to have full coverage (CI mode)
    python3 tools/check-conformance-coverage.py --require python --require csharp
"""

import argparse
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

# Make the script importable from tests under both filename forms.
sys.modules.setdefault("check_conformance_coverage", sys.modules[__name__])


# ─── parsing ──────────────────────────────────────────────────────────

_ID_PATTERN = re.compile(r"\b([A-Z]{3,5})-(\d{3})\b")
_HEADING_PREFIX = "### "


def parse_catalog_ids(catalog_path: Path) -> set[str]:
    """Return the set of XXX-NNN IDs declared as ### test headings in the catalog.

    We deliberately limit parsing to lines that start with `### ` so that
    references inside body prose (and the "Identifier prefixes" table) are
    ignored. The catalog's convention is one ### heading per test.
    """
    ids: set[str] = set()
    for raw_line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.startswith(_HEADING_PREFIX):
            continue
        for match in _ID_PATTERN.finditer(raw_line):
            ids.add(f"{match.group(1)}-{match.group(2)}")
    return ids


_PY_MARK_PATTERN = re.compile(r'@pytest\.mark\.conformance\(["\']([A-Z]{3,5}-\d{3})["\']\)')
_CS_TRAIT_PATTERN = re.compile(r'Trait\(\s*"Conformance"\s*,\s*"([A-Z]{3,5}-\d{3})"\s*\)')


def scrape_python_conformance_ids(directory: Path) -> set[str]:
    ids: set[str] = set()
    for path in directory.rglob("*.py"):
        for match in _PY_MARK_PATTERN.finditer(path.read_text(encoding="utf-8")):
            ids.add(match.group(1))
    return ids


def scrape_csharp_conformance_ids(directory: Path) -> set[str]:
    ids: set[str] = set()
    for path in directory.rglob("*.cs"):
        for match in _CS_TRAIT_PATTERN.finditer(path.read_text(encoding="utf-8")):
            ids.add(match.group(1))
    return ids


# ─── coverage math ────────────────────────────────────────────────────

def compute_gaps(catalog: set[str], coverage: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return {language: missing_ids} for every language with a non-empty gap."""
    return {
        lang: missing
        for lang, found in coverage.items()
        if (missing := catalog - found)
    }


# ─── language registry ────────────────────────────────────────────────

_SCRAPERS: dict[str, tuple[str, Callable[[Path], set[str]]]] = {
    "python":  ("langs/python/tests/conformance",        scrape_python_conformance_ids),
    "csharp":  ("langs/csharp/tests/VMx.Conformance.Tests", scrape_csharp_conformance_ids),
}


def collect_coverage(repo_root: Path) -> dict[str, set[str]]:
    """Walk every known language's conformance test directory and report IDs found.

    Languages whose conformance directory does not exist are skipped silently
    (the directory is a Phase 1+ concern; absence simply means "not yet
    implementing conformance").
    """
    coverage: dict[str, set[str]] = {}
    for lang, (rel_dir, scraper) in _SCRAPERS.items():
        directory = repo_root / rel_dir
        if not directory.is_dir():
            continue
        coverage[lang] = scraper(directory)
    return coverage


# ─── reporting ────────────────────────────────────────────────────────

def render_report(catalog: set[str], coverage: dict[str, set[str]], gaps: dict[str, set[str]]) -> str:
    lines: list[str] = []
    lines.append(f"Conformance catalog: {len(catalog)} IDs")
    if not coverage:
        lines.append("No language conformance directories found.")
        return "\n".join(lines)
    for lang in sorted(coverage):
        found = coverage[lang]
        missing = gaps.get(lang, set())
        lines.append(f"  {lang}: {len(found)}/{len(catalog)} covered")
        if missing:
            lines.append(f"    MISSING ({len(missing)}): " + ", ".join(sorted(missing)))
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: the parent of this script).",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        choices=list(_SCRAPERS.keys()),
        help="Language(s) that MUST have full conformance coverage. May be passed multiple times.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root).resolve()
    catalog_path = repo_root / "spec" / "12-conformance.md"
    if not catalog_path.is_file():
        print(f"ERROR: catalog not found at {catalog_path}", file=sys.stderr)
        return 2

    catalog = parse_catalog_ids(catalog_path)
    coverage = collect_coverage(repo_root)
    gaps = compute_gaps(catalog, coverage)
    print(render_report(catalog, coverage, gaps))

    required_gaps = {lang: missing for lang, missing in gaps.items() if lang in args.require}
    if required_gaps:
        print(file=sys.stderr)
        print(f"FAIL: required languages have conformance gaps: {sorted(required_gaps)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
