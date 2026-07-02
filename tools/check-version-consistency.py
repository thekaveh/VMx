#!/usr/bin/env python3
"""Cross-check manifest versions, compatibility matrix, and git tags.

Reads declared package versions from every flavor's manifest, parses the
compatibility matrix rows, lists git tags, and reports every mismatch.

Rules enforced:
  1. All flavor ``minSpecVersion`` fields must equal ``spec/VERSION``.
  2. Every version a manifest *claims* as shipped must have a matching
     git tag (e.g. ``csharp-v2.6.0``, ``python-v2.6.1``).
     ``spec/VERSION`` implies both ``spec-v<version>`` and ``v<version>``
     (the repo-wide tag).
  3. Every version a compatibility-matrix row *claims* must have a
     matching flavor tag (e.g. ``csharp-v2.5.0``).  A spec row also
     implies ``spec-v<X.Y.0>`` and ``v<X.Y.0>``.

In-development exemption:
  The current version — the one that EQUALS ``spec/VERSION`` — is being
  prepared on the release branch but is not tagged yet (tags are created at
  release time).  Tags whose embedded version equals ``spec/VERSION`` are
  therefore reported as "in development, untagged — OK" and do NOT cause a
  non-zero exit.  All OTHER ``major >= 2`` matrix rows / manifest versions
  still require a matching tag.

Exit codes:
    0  No mismatches detected.
    1  At least one mismatch found.
    2  A required source file is missing (spec/VERSION or
       compatibility-matrix.md).

Usage:
    python3 tools/check-version-consistency.py [--repo-root PATH]

Examples:
    # Default: discover repo root automatically, report, and exit 1 on issues.
    python3 tools/check-version-consistency.py

    # Explicit root (useful in CI when cwd differs):
    python3 tools/check-version-consistency.py --repo-root /workspace
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# ─── enforcement policy ───────────────────────────────────────────────

# Only hard-fail (exit 1) for missing tags when the version's major
# component is at least this value.  Pre-2.0 releases (1.0.x, 1.1.x)
# pre-date consistent tagging; absent tags for those rows are printed
# as informational notes and do NOT cause exit 1.
MIN_ENFORCED_MAJOR: int = 2

# ─── regexes ──────────────────────────────────────────────────────────

# Matches a semver triple like 2.6.0 or 1.12.3.
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")

# Matches the spec column of a matrix row like "2.6.x" or "1.1.x".
_SPEC_ROW_RE = re.compile(r"^(\d+\.\d+)\.x$")


# ─── helpers ──────────────────────────────────────────────────────────


def _tag_major(tag: str) -> int:
    """Return the major version component embedded in a tag name.

    Handles patterns like ``csharp-v2.6.0``, ``spec-v1.0.0``, ``v2.4.0``.
    Returns 0 for tags whose version cannot be parsed (treated as enforced,
    i.e. fail-safe).
    """
    m = re.search(r"[vV](\d+)\.\d+\.\d+", tag)
    return int(m.group(1)) if m else 0


def _tag_version(tag: str) -> str:
    """Return the ``X.Y.Z`` semver embedded in a tag name, or ``""`` if absent.

    Handles patterns like ``csharp-v3.0.0``, ``spec-v3.0.0``, ``v3.0.0``.
    Used to identify tags for the current (in-development) version, which is
    exempt from the tag requirement until it is tagged at release.
    """
    m = re.search(r"[vV](\d+\.\d+\.\d+)", tag)
    return m.group(1) if m else ""


# ─── manifest parsers ─────────────────────────────────────────────────


def parse_spec_version(repo_root: Path) -> str:
    """Return the trimmed version string from ``spec/VERSION``."""
    return (repo_root / "spec" / "VERSION").read_text(encoding="utf-8").strip()


def parse_csharp_versions(csproj_path: Path) -> dict[str, str]:
    """Extract package version metadata from a ``.csproj`` file."""
    text = csproj_path.read_text(encoding="utf-8")
    ver_m = re.search(r"<Version>([^<]+)</Version>", text)
    msv_m = re.search(r"<MinSpecVersion>([^<]+)</MinSpecVersion>", text)
    pkg_m = re.search(r"<PackageId>([^<]+)</PackageId>", text)
    return {
        "package_id": pkg_m.group(1).strip() if pkg_m else csproj_path.stem,
        "version": ver_m.group(1).strip() if ver_m else "",
        "min_spec_version": msv_m.group(1).strip() if msv_m else "",
        "tag_prefix": "csharp",
        "require_current_spec": "true" if csproj_path.stem == "VMx" else "false",
    }


def parse_python_versions(about_path: Path) -> dict[str, str]:
    """Extract ``__version__`` and ``__min_spec_version__`` from ``__about__.py``."""
    text = about_path.read_text(encoding="utf-8")
    ver_m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    msv_m = re.search(r'__min_spec_version__\s*=\s*["\']([^"\']+)["\']', text)
    return {
        "version": ver_m.group(1) if ver_m else "",
        "min_spec_version": msv_m.group(1) if msv_m else "",
    }


def parse_typescript_versions(pkg_path: Path, src_dir: Path) -> dict[str, str]:
    """Extract ``version`` from ``package.json`` and ``__minSpecVersion__`` from src."""
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    version = pkg.get("version", "")
    min_spec = ""
    _msv_re = re.compile(r'__minSpecVersion__\s*=\s*["\']([^"\']+)["\']')
    for ts_file in sorted(src_dir.rglob("*.ts")):
        m = _msv_re.search(ts_file.read_text(encoding="utf-8"))
        if m:
            min_spec = m.group(1)
            break
    return {"version": version, "min_spec_version": min_spec}


def parse_swift_versions(version_swift_path: Path) -> dict[str, str]:
    """Extract ``current`` and ``minSpecVersion`` from ``VMx/Version.swift``."""
    text = version_swift_path.read_text(encoding="utf-8")
    cur_m = re.search(r"static\s+let\s+current\s*=\s*[\"']([^\"']+)[\"']", text)
    msv_m = re.search(r"static\s+let\s+minSpecVersion\s*=\s*[\"']([^\"']+)[\"']", text)
    return {
        "version": cur_m.group(1) if cur_m else "",
        "min_spec_version": msv_m.group(1) if msv_m else "",
    }


def collect_manifests(repo_root: Path) -> dict[str, dict[str, str]]:
    """Collect version info from every flavor manifest that is present."""
    manifests: dict[str, dict[str, str]] = {}

    csharp_src = repo_root / "langs" / "csharp" / "src"
    if csharp_src.is_dir():
        for csproj in sorted(csharp_src.glob("*/*.csproj")):
            info = parse_csharp_versions(csproj)
            package_id = info.get("package_id") or csproj.stem
            key = "csharp" if package_id == "VMx" else f"csharp/{package_id}"
            manifests[key] = info

    about = repo_root / "langs" / "python" / "src" / "vmx" / "__about__.py"
    if about.is_file():
        manifests["python"] = {
            **parse_python_versions(about),
            "tag_prefix": "python",
            "require_current_spec": "true",
        }

    pkg = repo_root / "langs" / "typescript" / "package.json"
    ts_src = repo_root / "langs" / "typescript" / "src"
    if pkg.is_file():
        manifests["typescript"] = {
            **parse_typescript_versions(pkg, ts_src),
            "tag_prefix": "typescript",
            "require_current_spec": "true",
        }

    swift_ver = repo_root / "langs" / "swift" / "Sources" / "VMx" / "Version.swift"
    if swift_ver.is_file():
        manifests["swift"] = {
            **parse_swift_versions(swift_ver),
            "tag_prefix": "swift",
            "require_current_spec": "true",
        }

    return manifests


# ─── matrix parser ────────────────────────────────────────────────────


def parse_matrix(matrix_path: Path) -> list[dict[str, object]]:
    """Parse the main table from ``compatibility-matrix.md``.

    Returns a list of row dicts::

        [
            {
                "spec_row": "2.6.x",
                "csharp": ["2.6.0"],
                "python": ["2.6.1"],
                "typescript": ["2.6.0"],
                "swift": ["2.6.0"],
            },
            ...
        ]

    Cells containing ``—`` (em-dash) or ``-`` map to an empty list.
    Annotation parentheticals like ``(subset)`` are stripped before
    version extraction.  Range cells (e.g. ``1.1.0`` to ``1.2.0``) yield
    ``["1.1.0", "1.2.0"]``.
    """
    lines = matrix_path.read_text(encoding="utf-8").splitlines()
    header_idx: int | None = None

    # Locate the header row (contains "spec" and "csharp").
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) >= 5 and cells[0].strip().lower() == "spec":
            header_idx = i
            break

    if header_idx is None:
        return []

    rows: list[dict[str, object]] = []
    # Skip the header (+0) and separator (+1); data starts at +2.
    for line in lines[header_idx + 2 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        spec_row = cells[0].strip()
        if not _SPEC_ROW_RE.match(spec_row):
            continue

        row: dict[str, object] = {"spec_row": spec_row}
        for idx, flavor in enumerate(("csharp", "python", "typescript", "swift")):
            cell = cells[idx + 1].strip() if idx + 1 < len(cells) else ""
            # Strip annotation parentheticals like "(subset)".
            cell = re.sub(r"\s*\([^)]*\)", "", cell).strip()
            if cell in ("—", "-", ""):
                row[flavor] = []
            else:
                row[flavor] = _VERSION_RE.findall(cell)
        rows.append(row)

    return rows


# ─── git tags ─────────────────────────────────────────────────────────


def get_git_tags(repo_root: Path) -> set[str]:
    """Return the full set of git tags visible from ``repo_root``."""
    result = subprocess.run(
        ["git", "tag", "--list"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line.strip()}


# ─── consistency checks ───────────────────────────────────────────────


def check_min_spec_versions(
    spec_version: str,
    manifests: dict[str, dict[str, str]],
) -> list[str]:
    """Return one issue string per flavor whose ``minSpecVersion`` != ``spec/VERSION``."""
    issues: list[str] = []
    for flavor, info in sorted(manifests.items()):
        if info.get("require_current_spec", "true") == "false":
            continue
        msv = info.get("min_spec_version", "")
        if msv != spec_version:
            issues.append(f"  {flavor}: minSpecVersion={msv!r} but spec/VERSION={spec_version!r}")
    return issues


def find_missing_tags(
    spec_version: str,
    manifests: dict[str, dict[str, str]],
    matrix_rows: list[dict[str, object]],
    tags: set[str],
) -> dict[str, list[str]]:
    """Return a dict ``{missing_tag: [reason, ...]}`` for every absent tag.

    Sources contributing required tags:

    * ``spec/VERSION`` → ``spec-v<version>`` and ``v<version>``
    * each flavor manifest ``version`` → ``<flavor>-v<version>``
    * each matrix row flavor cell → ``<flavor>-v<cell_version>``
    * each matrix row spec column ``X.Y.x`` → ``spec-vX.Y.0`` and ``vX.Y.0``
    """
    missing: dict[str, list[str]] = {}

    def _want(tag: str, reason: str) -> None:
        if tag not in tags:
            missing.setdefault(tag, []).append(reason)

    # From spec/VERSION
    _want(f"spec-v{spec_version}", f"spec/VERSION={spec_version!r}")
    _want(f"v{spec_version}", f"spec/VERSION={spec_version!r} (repo-wide tag)")

    # From each flavor manifest
    for flavor, info in sorted(manifests.items()):
        ver = info.get("version", "")
        if ver:
            tag_prefix = info.get("tag_prefix") or flavor.split("/", 1)[0]
            _want(f"{tag_prefix}-v{ver}", f"{flavor} manifest version={ver!r}")

    # From matrix rows
    for row in matrix_rows:
        spec_row = str(row.get("spec_row", ""))
        m = _SPEC_ROW_RE.match(spec_row)
        if not m:
            continue
        spec_xy = m.group(1)
        spec_canonical = f"{spec_xy}.0"

        _want(f"spec-v{spec_canonical}", f"compatibility-matrix.md row {spec_row!r}")
        _want(f"v{spec_canonical}", f"compatibility-matrix.md row {spec_row!r} (repo-wide tag)")

        for flavor in ("csharp", "python", "typescript", "swift"):
            for ver in row.get(flavor, []):  # type: ignore[union-attr]
                _want(
                    f"{flavor}-v{ver}",
                    f"compatibility-matrix.md row {spec_row!r} [{flavor}={ver!r}]",
                )

    return missing


# ─── reporting ────────────────────────────────────────────────────────


def _render_indev_note(
    lines: list[str],
    spec_version: str,
    indev_tags: dict[str, list[str]],
) -> None:
    """Append the in-development (current, untagged) note to ``lines``."""
    lines.append("")
    lines.append(
        f"Note: {len(indev_tags)} tag(s) for the current in-development version"
        f" v{spec_version} absent (== spec/VERSION; tagged at release — OK):"
    )
    for tag in sorted(indev_tags):
        reasons = "; ".join(sorted(set(indev_tags[tag])))
        lines.append(f"  IN-DEV   {tag:<40}  ← {reasons}")


def _render_info_note(lines: list[str], info_tags: dict[str, list[str]]) -> None:
    """Append the pre-v2.0 informational note to ``lines``."""
    lines.append("")
    lines.append(
        f"Note: {len(info_tags)} pre-v{MIN_ENFORCED_MAJOR}.0 tag(s) absent"
        " (informational only; not enforced):"
    )
    for tag in sorted(info_tags):
        reasons = "; ".join(sorted(set(info_tags[tag])))
        lines.append(f"  INFO     {tag:<40}  ← {reasons}")


def render_report(
    spec_version: str,
    manifests: dict[str, dict[str, str]],
    matrix_rows: list[dict[str, object]],
    msv_issues: list[str],
    missing_tags: dict[str, list[str]],
    info_tags: dict[str, list[str]] | None = None,
    indev_tags: dict[str, list[str]] | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"spec/VERSION: {spec_version}")
    lines.append(f"Manifests found: {', '.join(sorted(manifests)) or '(none)'}")
    lines.append(f"Matrix rows parsed: {len(matrix_rows)}")
    lines.append("")

    if not msv_issues and not missing_tags:
        lines.append("OK: all manifest versions, matrix rows, and git tags are consistent.")
        if indev_tags:
            _render_indev_note(lines, spec_version, indev_tags)
        if info_tags:
            _render_info_note(lines, info_tags)
        return "\n".join(lines)

    if msv_issues:
        lines.append("minSpecVersion mismatches (all must equal spec/VERSION):")
        lines.extend(msv_issues)
        lines.append("")

    if missing_tags:
        lines.append(f"Missing git tags ({len(missing_tags)} total):  [claim  →  expected tag]")
        for tag in sorted(missing_tags):
            reasons = "; ".join(sorted(set(missing_tags[tag])))
            lines.append(f"  MISSING  {tag:<40}  ← {reasons}")

    if indev_tags:
        _render_indev_note(lines, spec_version, indev_tags)

    if info_tags:
        _render_info_note(lines, info_tags)

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (default: parent of this script).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root).resolve()

    # Guard: required files must exist before any parsing.
    spec_version_file = repo_root / "spec" / "VERSION"
    if not spec_version_file.is_file():
        print(f"ERROR: spec/VERSION not found at {spec_version_file}", file=sys.stderr)
        return 2

    matrix_file = repo_root / "compatibility-matrix.md"
    if not matrix_file.is_file():
        print(
            f"ERROR: compatibility-matrix.md not found at {matrix_file}",
            file=sys.stderr,
        )
        return 2

    spec_version = parse_spec_version(repo_root)
    manifests = collect_manifests(repo_root)
    matrix_rows = parse_matrix(matrix_file)
    tags = get_git_tags(repo_root)

    msv_issues = check_min_spec_versions(spec_version, manifests)
    all_missing = find_missing_tags(spec_version, manifests, matrix_rows, tags)

    # Carve out the current, in-development version first: tags whose embedded
    # semver equals spec/VERSION are not created until release, so their absence
    # is expected and must NOT fail the check.
    indev_missing = {t: r for t, r in all_missing.items() if _tag_version(t) == spec_version}
    remaining = {t: r for t, r in all_missing.items() if _tag_version(t) != spec_version}

    # Split the rest into enforced (major >= MIN_ENFORCED_MAJOR) and
    # informational (major < MIN_ENFORCED_MAJOR, e.g. pre-2.0 legacy rows).
    enforced_missing = {t: r for t, r in remaining.items() if _tag_major(t) >= MIN_ENFORCED_MAJOR}
    info_missing = {t: r for t, r in remaining.items() if _tag_major(t) < MIN_ENFORCED_MAJOR}

    report = render_report(
        spec_version,
        manifests,
        matrix_rows,
        msv_issues,
        enforced_missing,
        info_missing or None,
        indev_missing or None,
    )
    print(report)

    if msv_issues or enforced_missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
