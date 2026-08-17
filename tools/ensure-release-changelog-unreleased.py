#!/usr/bin/env python3
"""Restore VMx's canonical Unreleased section after Release Please runs."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

BRACKETED_HEADING = re.compile(
    r"^## \[([^]\n]+)\](?:\([^\n)]+\))?(?:[ \t].*)?$",
    re.MULTILINE,
)
NUMBERED_RELEASE = re.compile(r"\d+\.\d+\.\d+")
CANONICAL_UNRELEASED = "## [Unreleased]"


def _replace_atomically(path: Path, content: str) -> None:
    mode = path.stat().st_mode
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def ensure_unreleased(path: Path) -> bool:
    """Ensure *path* starts its bracketed release sections with Unreleased."""
    content = path.read_text(encoding="utf-8")
    headings = list(BRACKETED_HEADING.finditer(content))
    unreleased = [match for match in headings if match.group(1) == "Unreleased"]

    if len(unreleased) > 1:
        raise ValueError("changelog must contain exactly one [Unreleased] section")

    if unreleased:
        if unreleased[0].group(0) != CANONICAL_UNRELEASED:
            raise ValueError("[Unreleased] heading is not canonical")
        if headings[0] == unreleased[0]:
            return False

        unreleased_index = headings.index(unreleased[0])
        section_end = (
            headings[unreleased_index + 1].start()
            if unreleased_index + 1 < len(headings)
            else len(content)
        )
        if content[unreleased[0].end() : section_end].strip():
            raise ValueError("a misplaced [Unreleased] section must be empty")
        without_unreleased = content[: unreleased[0].start()] + content[section_end:]
        insertion = f"{CANONICAL_UNRELEASED}\n\n"
        repaired = (
            without_unreleased[: headings[0].start()]
            + insertion
            + without_unreleased[headings[0].start() :]
        )
        _replace_atomically(path, repaired)
        return True

    if not headings or NUMBERED_RELEASE.fullmatch(headings[0].group(1)) is None:
        raise ValueError("changelog must contain a first numbered release section")

    insertion = f"{CANONICAL_UNRELEASED}\n\n"
    repaired = content[: headings[0].start()] + insertion + content[headings[0].start() :]
    _replace_atomically(path, repaired)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("changelog", type=Path)
    args = parser.parse_args(argv)
    try:
        changed = ensure_unreleased(args.changelog)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print("restored [Unreleased]" if changed else "[Unreleased] already canonical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
