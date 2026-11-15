#!/usr/bin/env python3
"""Assert every Swift bundled fixture copy is byte-identical to its source of truth.

SwiftPM resources must live inside the target directory, so Swift keeps copies of
spec/fixtures/*.json under the library target's resources. All copies live in the
library bundle: the tests load them via `Bundle.module`, which resolves to the
library's bundle (the test target declares no resources, so no shadowing VMxTests
bundle is generated).

The inventory is derived from spec/fixtures/*.json at run time. Every spec fixture
needs a byte-identical copy in the Swift resources directory, unless that directory
lists the fixture in _COPY_DIRECTORIES as an explicit exemption. An extra JSON file
in the resources directory fails, and an exemption that names no spec fixture fails.
Exit 1 on any mismatch, missing copy, extra copy or stale exemption.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SPEC_DIRECTORY = "spec/fixtures"

# Copy directory -> spec fixtures that directory intentionally does not hold.
_COPY_DIRECTORIES: dict[str, frozenset[str]] = {
    # The library bundle ships every spec fixture.
    "langs/swift/Sources/VMx/Resources": frozenset(),
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
                f"FAIL: Swift fixture exemption names no spec fixture: {name} ({copy_rel})",
                file=sys.stderr,
            )
            failed = True
        expected = sources - exempt
        copies = _json_names(root / copy_rel)
        for name in sorted(expected - copies):
            print(
                f"FAIL: missing Swift fixture copy: {copy_rel}/{name}\n"
                f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
                file=sys.stderr,
            )
            failed = True
        for name in sorted(copies - expected):
            print(
                f"FAIL: unexpected Swift fixture copy: {copy_rel}/{name} "
                "(no spec fixture, or the fixture is exempt for this directory)",
                file=sys.stderr,
            )
            failed = True
        for name in sorted(expected & copies):
            source = root / SPEC_DIRECTORY / name
            swift_copy = root / copy_rel / name
            if source.read_bytes() != swift_copy.read_bytes():
                print(
                    f"FAIL: Swift fixture copy drifted from {SPEC_DIRECTORY}/{name}\n"
                    f"  source: {source}\n  copy:   {swift_copy}\n"
                    f"  Re-sync: cp {SPEC_DIRECTORY}/{name} {copy_rel}/{name}",
                    file=sys.stderr,
                )
                failed = True
                continue
            print(f"OK: {copy_rel}/{name} matches {SPEC_DIRECTORY}/{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
