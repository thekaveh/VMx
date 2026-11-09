#!/usr/bin/env python3
"""Reject optional chaining on a subscript result (``]?.``) in the repository's Swift code.

Apple Swift 6.4 (swiftlang-6.4.0.34.1) at ``-Onone`` can return a non-nil
value for a dictionary lookup with a missing key when the lookup is chained
straight into a member access. ``swift test`` builds at ``-Onone``. Bind the
lookup with ``if let`` or ``guard let`` before reading the member instead
(#1462, CONTRIBUTING.md).

The check is textual: it reports every ``]?.`` in a ``.swift`` file under
``langs/swift``, ``examples/swift`` and ``starters/swift-package``, and in the
root ``Package.swift``, comments and strings included. Build directories
(``.build``) are skipped.

Exit codes: 0 when no file contains the pattern, 1 when one does.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

PATTERN = "]?."
SWIFT_DIRS = ("langs/swift", "examples/swift", "starters/swift-package")
ROOT_FILES = ("Package.swift",)
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def swift_files(root: Path) -> Iterator[Path]:
    """Yield the checked Swift files under ``root`` in path order."""
    for name in ROOT_FILES:
        if (root / name).is_file():
            yield root / name
    for directory in SWIFT_DIRS:
        for path in sorted((root / directory).rglob("*.swift")):
            if ".build" not in path.relative_to(root).parts and path.is_file():
                yield path


def findings(root: Path) -> list[str]:
    """Return ``path:line: text`` for each line that contains the pattern."""
    result: list[str] = []
    for path in swift_files(root):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if PATTERN in line:
                result.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    found = findings(args.root)
    if not found:
        print(f"OK: no Swift file chains a member access onto a subscript ({PATTERN!r})")
        return 0
    for finding in found:
        print(finding)
    print(
        f"FAIL: {len(found)} line(s) chain a member access onto a subscript ({PATTERN!r}). "
        "Swift 6.4 at -Onone can return a non-nil value for a missing dictionary key "
        "here; bind the lookup with `if let` or `guard let` first (CONTRIBUTING.md, #1462).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
