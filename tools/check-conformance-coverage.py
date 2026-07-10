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

    # Require python and csharp to have full coverage
    python3 tools/check-conformance-coverage.py --require python --require csharp

    # CI mode: enforce every full-parity flavor
    python3 tools/check-conformance-coverage.py \
        --require python --require csharp --require typescript --require swift --require rust
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

# Swift: doc-comment or line-comment where the ID is the first token after the
# comment opener, followed on the same line by an em dash (—).  The marker
# convention used throughout langs/swift/Tests/**/*.swift is:
#
#   /// LIFE-001 — description
#   /// LIFE-013 (group path) — description   (parenthetical before the dash is OK)
#
# The em dash is required to distinguish intentional markers from in-comment
# mentions of IDs that are NOT claimed, e.g.:
#
#   /// LIFE-011 (table matches `lifecycle-transitions.json`) is NOT   ← no dash
#
# This also excludes:
#
#   // Claimed IDs: LIFE-001..007   (text before the ID, not the first token)
#   // and LIFE-011 are NOT claimed  (text before the ID)
#   // ── section header (COMP-025)  (decorator chars before the ID)
#
# Note: unlike the other scrapers, comment-form markers ARE valid for Swift —
# the doc-comment IS the marker, so no comment-suppression filtering is applied
# beyond the em-dash convention above.
_SWIFT_COMMENT_MARKER_PATTERN = re.compile(r"(?m)^[ \t]*///?[ \t]+([A-Z]{3,5}-\d{3})\b[^\n—]*—")

# Rust follows the Swift-style doc-comment convention in
# `langs/rust/tests/conformance/**/*.rs`:
#
#   /// LIFE-001 — description
#   #[test]
#   fn life_001_constructs() { ... }
#
# Markers must attach to a Rust test function so prose-only comments are not
# counted as conformance coverage.
_RUST_COMMENT_MARKER_PATTERN = re.compile(r"(?m)^[ \t]*///[ \t]+([A-Z]{3,5}-\d{3})\b[^\n—]*—")
_RUST_TEST_FN_PATTERN = re.compile(
    r"^(?:pub(?:\s*\([^)]*\))?\s+)?fn(?:\s+([A-Za-z_][A-Za-z0-9_]*)|\s*$)"
)

# Prefixes that look like conformance IDs but are NOT — e.g. `VMX-002` is an
# audit finding-id, which Swift test files legitimately reference in doc comments
# (`/// VMX-002 regression — ...`). They must not be mistaken for conformance markers.
_NON_CONFORMANCE_PREFIXES = frozenset({"VMX"})


def scrape_python_conformance_ids(directory: Path) -> set[str]:
    """Scrape Python conformance IDs, ignoring any marker preceded by # on the same line."""
    ids: set[str] = set()
    for path in directory.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _PY_MARK_PATTERN.finditer(text):
            # Slice from the most-recent newline (or BOF) up to the match start.
            # If a # appears in that prefix the decorator is inside a line comment.
            line_start = text.rfind("\n", 0, match.start()) + 1
            if (
                "#" not in text[line_start : match.start()]
                and match.group(1).split("-", 1)[0] not in _NON_CONFORMANCE_PREFIXES
            ):
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
            if (
                "//" not in cleaned[line_start : match.start()]
                and match.group(1).split("-", 1)[0] not in _NON_CONFORMANCE_PREFIXES
            ):
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
            if (
                "//" not in cleaned[line_start : match.start()]
                and match.group(1).split("-", 1)[0] not in _NON_CONFORMANCE_PREFIXES
            ):
                ids.add(match.group(1))
    return ids


def scrape_swift_conformance_ids(directory: Path) -> set[str]:
    """Scrape Swift conformance IDs from doc-comment markers.

    A marker is a line where `///` or `//` is immediately followed (with optional
    whitespace) by a conformance ID of the form `[A-Z]{3,5}-NNN`.  This matches
    the Swift test convention of annotating each test function with:

        /// LIFE-001 — description
        func testLife001...() { ... }

    Because the doc-comment IS the marker in Swift (unlike other flavors where
    a real code annotation is used), comment-form markers are intentionally valid.
    To avoid counting file-summary comments as coverage, the marker must attach
    to a Swift test function: only comment/attribute lines may appear between the
    marker and a following ``func test...`` declaration.
    """
    ids: set[str] = set()
    for path in directory.rglob("*.swift"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = _SWIFT_COMMENT_MARKER_PATTERN.match(line)
            if match is None or not _swift_marker_attaches_to_test(lines, index):
                continue
            ident = match.group(1)
            if ident.split("-", 1)[0] in _NON_CONFORMANCE_PREFIXES:
                continue  # audit finding-id reference (e.g. VMX-002), not a conformance marker
            ids.add(ident)
    return ids


def _swift_marker_attaches_to_test(lines: list[str], marker_index: int) -> bool:
    """Return True when a Swift marker is part of a test function doc block."""
    for line in lines[marker_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("func test"):
            return True
        if stripped.startswith("//") or stripped.startswith("@"):
            continue
        return False
    return False


def scrape_rust_conformance_ids(directory: Path) -> set[str]:
    """Scrape Rust conformance IDs from doc-comment markers attached to tests."""
    ids: set[str] = set()
    for path in directory.rglob("*.rs"):
        text = _mask_rust_non_code(path.read_text(encoding="utf-8"))
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = _RUST_COMMENT_MARKER_PATTERN.match(line)
            if match is None or not _rust_marker_attaches_to_test(lines, index):
                continue
            ident = match.group(1)
            if ident.split("-", 1)[0] in _NON_CONFORMANCE_PREFIXES:
                continue
            ids.add(ident)
    return ids


def _mask_rust_non_code(text: str) -> str:
    """Blank Rust block comments and strings while preserving lines.

    Line comments stay intact because ``///`` is the intentional marker syntax.
    Rust block comments can nest, so the C-style comment regex used by other
    scrapers is insufficient here.
    """
    masked = list(text)

    def blank(start: int, end: int) -> None:
        for position in range(start, end):
            if masked[position] not in "\r\n":
                masked[position] = " "

    index = 0
    while index < len(text):
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline + 1
            continue

        if text.startswith("/*", index):
            depth = 1
            end = index + 2
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            blank(index, end)
            index = end
            continue

        if text[index] == "r":
            delimiter = index + 1
            while delimiter < len(text) and text[delimiter] == "#":
                delimiter += 1
            if delimiter < len(text) and text[delimiter] == '"':
                hashes = text[index + 1 : delimiter]
                terminator = '"' + hashes
                closing = text.find(terminator, delimiter + 1)
                end = len(text) if closing == -1 else closing + len(terminator)
                blank(index, end)
                index = end
                continue

        if text[index] == '"':
            end = index + 1
            escaped = False
            while end < len(text):
                character = text[end]
                end += 1
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    break
            blank(index, end)
            index = end
            continue

        if text.startswith("'\"'", index):
            blank(index, index + 3)
            index += 3
            continue

        index += 1

    return "".join(masked)


def _rust_marker_attaches_to_test(lines: list[str], marker_index: int) -> bool:
    """Return True when a Rust marker is part of a #[test] function doc block."""
    saw_test_attribute = False
    for index, line in enumerate(lines[marker_index + 1 :], start=marker_index + 1):
        stripped = line.strip()
        if stripped == "#[test]":
            saw_test_attribute = True
            continue
        if saw_test_attribute:
            match = _RUST_TEST_FN_PATTERN.match(stripped)
            if match is not None:
                if match.group(1) is not None:
                    return True
                for continuation in lines[index + 1 :]:
                    continued = continuation.strip()
                    if not continued or continued.startswith("//"):
                        continue
                    return re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*\(", continued) is not None
        if stripped.startswith("///") or stripped.startswith("#["):
            continue
        return False
    return False


def load_subset_manifest(manifest_path: Path) -> set[str]:
    """Load the sorted list of IDs from a subset manifest file.

    Lines starting with `#` are treated as comments and ignored.
    Blank lines are skipped.
    """
    ids: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


# ─── coverage math ────────────────────────────────────────────────────


def compute_gaps(
    catalog: set[str],
    coverage: dict[str, set[str]],
    subsets: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    """Return {language: problematic_ids} for every language with issues.

    For full-parity languages: problematic = catalog - coverage (missing IDs).
    For subset languages (those present in `subsets`): problematic is the union of
      - bogus:    test IDs not in the catalog (typos / invalid references)
      - unlisted: test IDs in the catalog but absent from the manifest
      - untested: manifest IDs with no corresponding test marker
    """
    _subsets = subsets or {}
    result: dict[str, set[str]] = {}
    for lang, found in coverage.items():
        if lang in _subsets:
            manifest = _subsets[lang]
            bogus = found - catalog
            unlisted = (found & catalog) - manifest
            untested = manifest - found
            problematic = bogus | unlisted | untested
        else:
            problematic = catalog - found
        if problematic:
            result[lang] = problematic
    return result


# ─── language registry ────────────────────────────────────────────────

# To add a new language: define a regex pattern matching its conformance-mark syntax,
# add a thin scraper wrapper, and register `(rel_dir, scraper, manifest_rel)` here
# under the language key.  `manifest_rel` is `None` for full-parity languages; for
# subset languages it is the repo-root-relative path to the subset manifest file.
# The CLI's `--require` automatically picks up the new key via `choices`.
_SCRAPERS: dict[str, tuple[str, Callable[[Path], set[str]], str | None]] = {
    "python": ("langs/python/tests/conformance", scrape_python_conformance_ids, None),
    "csharp": (
        "langs/csharp/tests/VMx.Conformance.Tests",
        scrape_csharp_conformance_ids,
        None,
    ),
    "typescript": (
        "langs/typescript/tests/conformance",
        scrape_typescript_conformance_ids,
        None,
    ),
    "swift": (
        "langs/swift/Tests/VMxTests",
        scrape_swift_conformance_ids,
        None,
    ),
    "rust": (
        "langs/rust/tests/conformance",
        scrape_rust_conformance_ids,
        None,
    ),
}


def collect_coverage(
    repo_root: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Walk every known language's conformance test directory and report IDs found.

    Returns a pair ``(coverage, subsets)`` where:

    - ``coverage`` maps each language to its set of scraped test IDs.
    - ``subsets`` maps subset languages (those with a ``manifest_rel`` entry in
      ``_SCRAPERS``) to their declared manifest IDs, loaded from the manifest
      file if it is present.

    Languages whose conformance directory does not exist are skipped silently
    (absence simply means "not yet implementing conformance").
    """
    coverage: dict[str, set[str]] = {}
    subsets: dict[str, set[str]] = {}
    for lang, (rel_dir, scraper, manifest_rel) in _SCRAPERS.items():
        directory = repo_root / rel_dir
        if not directory.is_dir():
            continue
        coverage[lang] = scraper(directory)
        if manifest_rel is not None:
            manifest_path = repo_root / manifest_rel
            if manifest_path.is_file():
                subsets[lang] = load_subset_manifest(manifest_path)
    return coverage, subsets


# ─── reporting ────────────────────────────────────────────────────────


def render_report(
    catalog: set[str],
    coverage: dict[str, set[str]],
    gaps: dict[str, set[str]],
    subsets: dict[str, set[str]] | None = None,
) -> str:
    _subsets = subsets or {}
    lines: list[str] = []
    lines.append(f"Conformance catalog: {len(catalog)} IDs")
    if not coverage:
        lines.append("No language conformance directories found.")
        return "\n".join(lines)
    for lang in sorted(coverage):
        found = coverage[lang]
        if lang in _subsets:
            manifest = _subsets[lang]
            covered = found & manifest
            bogus = found - catalog
            unlisted = (found & catalog) - manifest
            untested = manifest - found
            lines.append(f"  {lang}: {len(covered)}/{len(manifest)} (declared subset)")
            if bogus:
                lines.append(
                    f"    BOGUS ({len(bogus)}): "
                    + ", ".join(sorted(bogus))
                    + " (test IDs not in the catalog)"
                )
            if unlisted:
                lines.append(
                    f"    UNLISTED ({len(unlisted)}): "
                    + ", ".join(sorted(unlisted))
                    + " (test IDs not declared in the subset manifest)"
                )
            if untested:
                lines.append(
                    f"    UNTESTED ({len(untested)}): "
                    + ", ".join(sorted(untested))
                    + " (manifest IDs with no test marker)"
                )
        else:
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
    coverage, subsets = collect_coverage(repo_root)

    # Required-language sanity: a required language with no conformance directory
    # is a hard error, not a "0/N covered" warning. CI authors wiring --require
    # expect a missing directory to block the run.
    for lang in args.require:
        if lang not in coverage:
            rel_dir, _, _ = _SCRAPERS[lang]
            print(
                f"ERROR: --require {lang}: conformance directory not found at "
                f"{repo_root / rel_dir}",
                file=sys.stderr,
            )
            return 2
        # For subset languages, the manifest must also be present when --require is used.
        _, _, manifest_rel = _SCRAPERS[lang]
        if manifest_rel is not None and lang not in subsets:
            manifest_path = repo_root / manifest_rel
            print(
                f"ERROR: --require {lang}: subset manifest not found at {manifest_path}",
                file=sys.stderr,
            )
            return 2

    gaps = compute_gaps(catalog, coverage, subsets)
    print(render_report(catalog, coverage, gaps, subsets))

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
