#!/usr/bin/env python3
"""Assert the Swift bundled fixture copy is byte-identical to the source of truth.

SwiftPM resources must live inside the target directory, so Swift keeps a copy of
spec/fixtures/lifecycle-transitions.json under Sources/VMx/Resources/. This guards
against the two drifting. Exit 1 on mismatch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def main() -> int:
    root = repo_root()
    source = root / "spec" / "fixtures" / "lifecycle-transitions.json"
    swift_copy = (
        root / "langs" / "swift" / "Sources" / "VMx" / "Resources" / "lifecycle-transitions.json"
    )
    if not swift_copy.exists():
        print(f"FAIL: missing Swift fixture copy: {swift_copy}", file=sys.stderr)
        return 1
    if source.read_bytes() != swift_copy.read_bytes():
        print(
            "FAIL: Swift fixture copy drifted from spec/fixtures/lifecycle-transitions.json\n"
            f"  source: {source}\n  copy:   {swift_copy}\n"
            "  Re-sync: cp spec/fixtures/lifecycle-transitions.json "
            "langs/swift/Sources/VMx/Resources/lifecycle-transitions.json",
            file=sys.stderr,
        )
        return 1
    print("OK: Swift fixture copy matches spec/fixtures/lifecycle-transitions.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
