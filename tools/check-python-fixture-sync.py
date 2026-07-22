#!/usr/bin/env python3
"""Assert Python's bundled runtime/test fixtures match the spec sources."""

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
        "langs/python/src/vmx/lifecycle/_data/lifecycle-transitions.json",
    ),
    *[
        (
            f"spec/fixtures/{name}",
            f"langs/python/tests/conformance/fixtures/data/{name}",
        )
        for name in (
            "command-truthtable.json",
            "derived-properties.json",
            "lifecycle-transitions.json",
            "message-ordering.json",
        )
    ],
]


def main() -> int:
    root = repo_root()
    failed = False
    for source_rel, copy_rel in _FIXTURE_PAIRS:
        source = root / source_rel
        packaged_copy = root / copy_rel
        if not packaged_copy.exists():
            print(f"FAIL: missing Python fixture copy: {packaged_copy}", file=sys.stderr)
            failed = True
            continue
        if source.read_bytes() != packaged_copy.read_bytes():
            print(
                f"FAIL: Python fixture copy drifted from {source_rel}\n"
                f"  source: {source}\n  copy:   {packaged_copy}\n"
                f"  Re-sync: cp {source_rel} {copy_rel}",
                file=sys.stderr,
            )
            failed = True
            continue
        print(f"OK: {copy_rel} matches {source_rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
