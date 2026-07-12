#!/usr/bin/env python3
"""Assert Rust's bundled runtime fixture is byte-identical to the spec source."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


_FIXTURE_PAIRS: list[tuple[str, str]] = [
    (
        "spec/fixtures/lifecycle-transitions.json",
        "langs/rust/src/fixtures/lifecycle-transitions.json",
    ),
]


def main() -> int:
    root = repo_root()
    failed = False
    for source_rel, copy_rel in _FIXTURE_PAIRS:
        source = root / source_rel
        rust_copy = root / copy_rel
        if not rust_copy.exists():
            print(f"FAIL: missing Rust fixture copy: {rust_copy}", file=sys.stderr)
            failed = True
            continue
        if source.read_bytes() != rust_copy.read_bytes():
            print(
                f"FAIL: Rust fixture copy drifted from {source_rel}\n"
                f"  source: {source}\n  copy:   {rust_copy}\n"
                f"  Re-sync: cp {source_rel} {copy_rel}",
                file=sys.stderr,
            )
            failed = True
            continue
        print(f"OK: {copy_rel} matches {source_rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
