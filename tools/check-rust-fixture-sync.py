#!/usr/bin/env python3
"""Assert Rust's bundled runtime/test fixtures match the spec sources.

The inventory is derived from spec/fixtures/*.json at run time. Every spec fixture
needs a byte-identical copy in the Rust copy directory, unless that directory lists
the fixture in _COPY_DIRECTORIES as an explicit exemption. An extra JSON file in the
copy directory fails, and an exemption that names no spec fixture fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPEC_DIRECTORY = "spec/fixtures"

# Copy directory -> spec fixtures that directory intentionally does not hold.
_COPY_DIRECTORIES: dict[str, frozenset[str]] = {
    # The published crate ships every spec fixture.
    "langs/rust/src/fixtures": frozenset(),
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
    for copy_rel, exempt in _COPY_DIRECTORIES.items():
        for name in sorted(exempt - sources):
            print(
                f"FAIL: Rust fixture exemption names no spec fixture: {name} ({copy_rel})",
                file=sys.stderr,
            )
            failed = True
        expected = sources - exempt
        copies = _json_names(root / copy_rel)
        for name in sorted(expected - copies):
            print(
                f"FAIL: missing Rust fixture copy: {copy_rel}/{name}\n"
                f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
                file=sys.stderr,
            )
            failed = True
        for name in sorted(copies - expected):
            print(
                f"FAIL: unexpected Rust fixture copy: {copy_rel}/{name} "
                "(no spec fixture, or the fixture is exempt for this directory)",
                file=sys.stderr,
            )
            failed = True
        for name in sorted(expected & copies):
            source = root / SPEC_DIRECTORY / name
            rust_copy = root / copy_rel / name
            if source.read_bytes() != rust_copy.read_bytes():
                print(
                    f"FAIL: Rust fixture copy drifted from {SPEC_DIRECTORY}/{name}\n"
                    f"  source: {source}\n  copy:   {rust_copy}\n"
                    f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
                    file=sys.stderr,
                )
                failed = True
                continue
            print(f"OK: {copy_rel}/{name} matches {SPEC_DIRECTORY}/{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
