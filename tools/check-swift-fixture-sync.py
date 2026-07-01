#!/usr/bin/env python3
"""Assert every Swift bundled fixture copy is byte-identical to its source of truth.

SwiftPM resources must live inside the target directory, so Swift keeps copies of
spec/fixtures/*.json under the relevant target's resources:

  - lifecycle-transitions.json → Sources/VMx/Resources/ (LIFE-011)
  - derived-properties.json    → Sources/VMx/Resources/ (DPROP-012)
  - command-truthtable.json    → Sources/VMx/Resources/ (CMD-007)
  - message-ordering.json      → Sources/VMx/Resources/ (HUB-006)

All live in the library bundle: the tests load them via `Bundle.module`, which
resolves to the library's bundle (the test target declares no resources, so no
shadowing VMxTests bundle is generated).

This guards against any copy drifting from its `spec/fixtures/` original. Exit 1
if any copy mismatches (or is missing).
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


# (spec source, swift copy) pairs — every Swift fixture copy that must stay in
# lockstep with its spec/fixtures/ original. Add a row here when a new fixture is
# bundled into a Swift target.
_FIXTURE_PAIRS: list[tuple[str, str]] = [
    (
        "spec/fixtures/lifecycle-transitions.json",
        "langs/swift/Sources/VMx/Resources/lifecycle-transitions.json",
    ),
    (
        "spec/fixtures/derived-properties.json",
        "langs/swift/Sources/VMx/Resources/derived-properties.json",
    ),
    (
        "spec/fixtures/command-truthtable.json",
        "langs/swift/Sources/VMx/Resources/command-truthtable.json",
    ),
    (
        "spec/fixtures/message-ordering.json",
        "langs/swift/Sources/VMx/Resources/message-ordering.json",
    ),
]


def main() -> int:
    root = repo_root()
    failed = False
    for source_rel, copy_rel in _FIXTURE_PAIRS:
        source = root / source_rel
        swift_copy = root / copy_rel
        if not swift_copy.exists():
            print(f"FAIL: missing Swift fixture copy: {swift_copy}", file=sys.stderr)
            failed = True
            continue
        if source.read_bytes() != swift_copy.read_bytes():
            print(
                f"FAIL: Swift fixture copy drifted from {source_rel}\n"
                f"  source: {source}\n  copy:   {swift_copy}\n"
                f"  Re-sync: cp {source_rel} {copy_rel}",
                file=sys.stderr,
            )
            failed = True
            continue
        print(f"OK: {copy_rel} matches {source_rel}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
