#!/usr/bin/env python3
"""Assert every tracked flavor copy of a spec fixture is byte-identical to its source.

The inventory is every top-level spec/fixtures/*.json file, read at run time. Each
copy directory in _COPY_DIRECTORIES must hold a byte-identical copy of every spec
fixture, except the fixtures that _NOT_COPIED exempts for that directory. The check
fails on a missing copy, an extra JSON file, a byte drift, an exemption that names
no spec fixture, and an exemption whose label names no copy directory. Exit 2 when
the repository root cannot be located.

Python, Rust and Swift copies are tracked because a published package cannot read
spec/. TypeScript and C# copy the whole spec/fixtures directory by glob at build time,
so they have no tracked copy here.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPEC_DIRECTORY = "spec/fixtures"

# Label -> tracked copy directory. Each label names one flavor copy in messages.
_COPY_DIRECTORIES: dict[str, str] = {
    "python-runtime": "langs/python/src/vmx/lifecycle/_data",
    "python-tests": "langs/python/tests/conformance/fixtures/data",
    "rust": "langs/rust/src/fixtures",
    "swift": "langs/swift/Sources/VMx/Resources",
}

# Label -> spec fixtures that copy directory intentionally does not hold.
_NOT_COPIED: dict[str, frozenset[str]] = {
    # The lifecycle runtime loads only lifecycle-transitions.json.
    "python-runtime": frozenset(
        {
            "command-truthtable.json",
            "derived-properties.json",
            "message-ordering.json",
        }
    ),
}


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return Path(out.stdout.strip())


def _json_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {path.name for path in directory.iterdir() if path.suffix == ".json"}


def _check_copy_directory(
    root: Path, label: str, copy_rel: str, exempt: frozenset[str], sources: set[str]
) -> bool:
    """Print one line per problem in a copy directory and return True when it passed."""
    passed = True
    for name in sorted(exempt - sources):
        print(
            f"FAIL: {label} fixture exemption names no spec fixture: {name}",
            file=sys.stderr,
        )
        passed = False
    expected = sources - exempt
    copies = _json_names(root / copy_rel)
    for name in sorted(expected - copies):
        print(
            f"FAIL: missing {label} fixture copy: {copy_rel}/{name}\n"
            f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
            file=sys.stderr,
        )
        passed = False
    for name in sorted(copies - expected):
        print(
            f"FAIL: unexpected {label} fixture copy: {copy_rel}/{name} "
            "(no spec fixture, or the fixture is exempt for this directory)",
            file=sys.stderr,
        )
        passed = False
    for name in sorted(expected & copies):
        source = root / SPEC_DIRECTORY / name
        copy = root / copy_rel / name
        if source.read_bytes() != copy.read_bytes():
            print(
                f"FAIL: {label} fixture copy drifted from {SPEC_DIRECTORY}/{name}\n"
                f"  source: {source}\n  copy:   {copy}\n"
                f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
                file=sys.stderr,
            )
            passed = False
            continue
        print(f"OK: {label} {copy_rel}/{name} matches {SPEC_DIRECTORY}/{name}")
    return passed


def main() -> int:
    try:
        root = repo_root()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: unable to locate repository root: {error}", file=sys.stderr)
        return 2
    sources = _json_names(root / SPEC_DIRECTORY)
    if not sources:
        print(f"FAIL: no fixtures found under {SPEC_DIRECTORY}", file=sys.stderr)
        return 1
    failed = False
    for label in sorted(set(_NOT_COPIED) - set(_COPY_DIRECTORIES)):
        print(f"FAIL: fixture exemption names no copy directory: {label}", file=sys.stderr)
        failed = True
    for label, copy_rel in _COPY_DIRECTORIES.items():
        exempt = _NOT_COPIED.get(label, frozenset())
        if not _check_copy_directory(root, label, copy_rel, exempt, sources):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
