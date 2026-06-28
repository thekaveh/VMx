#!/usr/bin/env python3
"""Cross-language conformance coverage check.

Parses spec/12-conformance.md for every `XXX-NNN` conformance ID, then walks each
active language's conformance test directory (registered in `_SCRAPERS`) and verifies
every ID has a matching test. Reports gaps to stdout and returns a non-zero exit code
if any language passed via --require has gaps, or if a required language has no
conformance directory at all.

Exit codes:
    0  All required languages at full coverage (or no --require given).
    1  At least one required language has conformance gaps.
    2  Catalog file not found, required language has no conformance directory,
       or invalid --require argument.

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

# ─── parsing ──────────────────────────────────────────────────────────

_ID_PATTERN = re.compile(r"\b([A-Z]{3,5})-(\d{3})\b")
_HEADING_PREFIX = "### "

# Scenario-contract prefixes that catalog assertions for EXAMPLE APPS rather
# than the language-neutral library. Their tests live under `examples/<lang>/...`
# instead of `langs/<lang>/tests/conformance/`, so the library-conformance
# scraper would always report them as missing. We exclude them from the catalog
# the per-flavor scraper compares against. The IDs still appear in
# `spec/12-conformance.md` (one ### heading per scenario) for documentation +
# cross-flavor parity; example-app suites cover them separately.
_SCENARIO_PREFIXES: frozenset[str] = frozenset({"THEME"})


def parse_catalog_ids(catalog_path: Path) -> set[str]:
    """Return the set of XXX-NNN IDs declared as ### test headings in the catalog.

    We deliberately limit parsing to lines that start with `### ` so that
    references inside body prose (and the "Identifier prefixes" table) are
    ignored. The catalog's convention is one ### heading per test.

    IDs whose prefix matches a scenario-contract family (see
    `_SCENARIO_PREFIXES`) are EXCLUDED — those live in example-app test trees,
    not `langs/<lang>/tests/conformance/`, and would otherwise show up as
    permanent gaps in cross-flavor coverage.
    """
    ids: set[str] = set()
    for raw_line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.startswith(_HEADING_PREFIX):
            continue
        for match in _ID_PATTERN.finditer(raw_line):
            prefix = match.group(1)
            if prefix in _SCENARIO_PREFIXES:
                continue
            ids.add(f"{match.group(1)}-{match.group(2)}")
    return ids


_PY_MARK_PATTERN = re.compile(
    r'@pytest\.mark\.conformance\(\s*["\']([A-Z]{3,5}-\d{3})["\']\s*(?:,[\s\S]*?)?\)',
    re.DOTALL,
)
_CS_TRAIT_PATTERN = re.compile(
    r'\[[^\[\]]*?Trait\(\s*"Conformance"\s*,\s*"([A-Z]{3,5}-\d{3})"\s*\)',
)
# TypeScript: `describe("XXX-NNN", ...)` — the ID is the entire describe label.
_TS_DESCRIBE_PATTERN = re.compile(
    r'describe\(\s*["\']([A-Z]{3,5}-\d{3})["\']\s*,',
)

# Matches C-style block comments (/* ... */), including multi-line ones.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def scrape_python_conformance_ids(directory: Path) -> set[str]:
    """Scrape Python conformance IDs, ignoring any marker preceded by # on the same line."""
    ids: set[str] = set()
    for path in directory.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _PY_MARK_PATTERN.finditer(text):
            # Slice from the most-recent newline (or BOF) up to the match start.
            # If a # appears in that prefix the decorator is inside a line comment.
            line_start = text.rfind("\n", 0, match.start()) + 1
            if "#" not in text[line_start : match.start()]:
                ids.add(match.group(1))
    return ids


def scrape_csharp_conformance_ids(directory: Path) -> set[str]:
    """Scrape C# conformance IDs, ignoring markers inside /* */ blocks or after // on a line."""
    ids: set[str] = set()
    for path in directory.rglob("*.cs"):
        text = path.read_text(encoding="utf-8")
        # Remove block comments first so their contents never reach the pattern.
        cleaned = _BLOCK_COMMENT_RE.sub("", text)
        for match in _CS_TRAIT_PATTERN.finditer(cleaned):
            line_start = cleaned.rfind("\n", 0, match.start()) + 1
            if "//" not in cleaned[line_start : match.start()]:
                ids.add(match.group(1))
    return ids


def scrape_typescript_conformance_ids(directory: Path) -> set[str]:
    """Scrape TypeScript conformance IDs, ignoring markers in /* */ blocks or after //."""
    ids: set[str] = set()
    for path in directory.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        # Remove block comments first so their contents never reach the pattern.
        cleaned = _BLOCK_COMMENT_RE.sub("", text)
        for match in _TS_DESCRIBE_PATTERN.finditer(cleaned):
            line_start = cleaned.rfind("\n", 0, match.start()) + 1
            if "//" not in cleaned[line_start : match.start()]:
                ids.add(match.group(1))
    return ids


# ─── coverage math ────────────────────────────────────────────────────


def compute_gaps(catalog: set[str], coverage: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return {language: missing_ids} for every language with a non-empty gap."""
    return {lang: missing for lang, found in coverage.items() if (missing := catalog - found)}


# ─── language registry ────────────────────────────────────────────────

# To add a new language: define a regex pattern matching its conformance-mark syntax,
# add a thin scraper wrapper, and register `(rel_dir, scraper)` here under the
# language key. The CLI's `--require` automatically picks up the new key via `choices`.
_SCRAPERS: dict[str, tuple[str, Callable[[Path], set[str]]]] = {
    "python": ("langs/python/tests/conformance", scrape_python_conformance_ids),
    "csharp": (
        "langs/csharp/tests/VMx.Conformance.Tests",
        scrape_csharp_conformance_ids,
    ),
    "typescript": (
        "langs/typescript/tests/conformance",
        scrape_typescript_conformance_ids,
    ),
}


def collect_coverage(repo_root: Path) -> dict[str, set[str]]:
    """Walk every known language's conformance test directory and report IDs found.

    Languages whose conformance directory does not exist are skipped silently
    (absence simply means "not yet implementing conformance").
    """
    coverage: dict[str, set[str]] = {}
    for lang, (rel_dir, scraper) in _SCRAPERS.items():
        directory = repo_root / rel_dir
        if not directory.is_dir():
            continue
        coverage[lang] = scraper(directory)
    return coverage


# ─── reporting ────────────────────────────────────────────────────────


def render_report(
    catalog: set[str], coverage: dict[str, set[str]], gaps: dict[str, set[str]]
) -> str:
    lines: list[str] = []
    lines.append(f"Conformance catalog: {len(catalog)} IDs")
    if not coverage:
        lines.append("No language conformance directories found.")
        return "\n".join(lines)
    for lang in sorted(coverage):
        found = coverage[lang]
        covered = found & catalog
        orphans = found - catalog
        missing = gaps.get(lang, set())
        lines.append(f"  {lang}: {len(covered)}/{len(catalog)} covered")
        if missing:
            lines.append(f"    MISSING ({len(missing)}): " + ", ".join(sorted(missing)))
        if orphans:
            lines.append(
                f"    ORPHAN ({len(orphans)}): "
                + ", ".join(sorted(orphans))
                + " (tests reference IDs not in the catalog)"
            )
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
        help=(
            "Language(s) that MUST have full conformance coverage; tool exits 1 on any gap. "
            "Omitting --require makes the tool report-only (always exits 0). "
            "May be passed multiple times."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root).resolve()
    catalog_path = repo_root / "spec" / "12-conformance.md"
    if not catalog_path.is_file():
        print(f"ERROR: catalog not found at {catalog_path}", file=sys.stderr)
        return 2

    catalog = parse_catalog_ids(catalog_path)
    coverage = collect_coverage(repo_root)

    # Required-language sanity: a required language with no conformance directory
    # is a hard error, not a "0/N covered" warning. CI authors wiring --require
    # expect a missing directory to block the run.
    for lang in args.require:
        if lang not in coverage:
            rel_dir, _ = _SCRAPERS[lang]
            print(
                f"ERROR: --require {lang}: conformance directory not found at "
                f"{repo_root / rel_dir}",
                file=sys.stderr,
            )
            return 2

    gaps = compute_gaps(catalog, coverage)
    print(render_report(catalog, coverage, gaps))

    required_gaps = {lang: missing for lang, missing in gaps.items() if lang in args.require}
    if required_gaps:
        print(file=sys.stderr)
        print(
            f"FAIL: required languages have conformance gaps: {sorted(required_gaps)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
