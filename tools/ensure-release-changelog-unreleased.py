#!/usr/bin/env python3
"""Restore VMx's canonical Unreleased section after Release Please runs.

The script also rewrites the Markdown that Release Please generates into the
form that the pinned mdformat check in ``conformance.yml`` accepts: ``-`` for
top-level bullets and one blank line between blocks (#1391). It uses only the
standard library, so the release workflow needs no extra install.
"""

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
FENCE_OPENING = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def normalize_release_please_markdown(content: str) -> str:
    """Rewrite Release Please's ``*`` bullets and blank-line runs as mdformat does.

    Fenced code blocks stay unchanged.
    """
    lines = content.split("\n")
    normalized: list[str] = []
    fence = ""
    for line in lines:
        if fence:
            normalized.append(line)
            if line.strip().startswith(fence) and not line.strip().strip(fence[0]):
                fence = ""
            continue
        opening = FENCE_OPENING.match(line)
        if opening:
            fence = opening.group(1)
            normalized.append(line)
            continue
        if not line.strip():
            if normalized and normalized[-1] == "":
                continue
            normalized.append("")
            continue
        if line.startswith("* "):
            line = "- " + line[2:]
        normalized.append(line)
    return "\n".join(normalized)


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
    """Ensure *path* starts its bracketed release sections with Unreleased.

    The rewritten file also gets the Release Please normalization above.
    Returns whether the file changed.
    """
    content = path.read_text(encoding="utf-8")
    repaired = _repair_unreleased(content)
    normalized = normalize_release_please_markdown(repaired)
    if normalized == content:
        return False
    _replace_atomically(path, normalized)
    return True


def _repair_unreleased(content: str) -> str:
    """Return *content* with one empty [Unreleased] before the first release."""
    headings = list(BRACKETED_HEADING.finditer(content))
    unreleased = [match for match in headings if match.group(1) == "Unreleased"]

    if len(unreleased) > 1:
        raise ValueError("changelog must contain exactly one [Unreleased] section")

    if unreleased:
        if unreleased[0].group(0) != CANONICAL_UNRELEASED:
            raise ValueError("[Unreleased] heading is not canonical")
        unreleased_index = headings.index(unreleased[0])
        section_end = (
            headings[unreleased_index + 1].start()
            if unreleased_index + 1 < len(headings)
            else len(content)
        )
        if content[unreleased[0].end() : section_end].strip():
            raise ValueError("[Unreleased] section must be empty")

        numbered_headings = [heading for heading in headings if heading != unreleased[0]]
        if (
            not numbered_headings
            or NUMBERED_RELEASE.fullmatch(numbered_headings[0].group(1)) is None
        ):
            raise ValueError("changelog must have a first numbered release section")
        if headings[0] == unreleased[0]:
            return content

        without_unreleased = content[: unreleased[0].start()] + content[section_end:]
        insertion = f"{CANONICAL_UNRELEASED}\n\n"
        return (
            without_unreleased[: headings[0].start()]
            + insertion
            + without_unreleased[headings[0].start() :]
        )

    if not headings or NUMBERED_RELEASE.fullmatch(headings[0].group(1)) is None:
        raise ValueError("changelog must contain a first numbered release section")

    insertion = f"{CANONICAL_UNRELEASED}\n\n"
    return content[: headings[0].start()] + insertion + content[headings[0].start() :]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("changelog", type=Path)
    args = parser.parse_args(argv)
    try:
        changed = ensure_unreleased(args.changelog)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "restored [Unreleased] and normalized the changelog"
        if changed
        else "[Unreleased] and changelog already canonical"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
