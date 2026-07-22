#!/usr/bin/env python3
"""Prevent release-please from proposing a Python version downgrade."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SOURCE_PATH = Path("langs/python/src/vmx/__about__.py")
_MANIFEST_PATH = Path(".release-please-manifest.json")
_PACKAGE_PATH = "langs/python"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


@dataclass(frozen=True)
class ReleaseState:
    """The Python source and last-published versions known to release-please."""

    ready: bool
    source_version: str
    published_version: str
    reason: str


def check_state(root: Path) -> ReleaseState:
    """Return whether release-please can safely maintain the Python release PR."""
    source_text = (root / _SOURCE_PATH).read_text(encoding="utf-8")
    match = _VERSION_RE.search(source_text)
    if match is None:
        raise ValueError(f"unable to find __version__ in {_SOURCE_PATH}")
    source_version = match.group(1)

    manifest = json.loads((root / _MANIFEST_PATH).read_text(encoding="utf-8"))
    published_version = manifest.get(_PACKAGE_PATH)
    if not isinstance(published_version, str) or not published_version:
        raise ValueError(f"{_MANIFEST_PATH} has no {_PACKAGE_PATH!r} version")

    if source_version == published_version:
        return ReleaseState(
            ready=True,
            source_version=source_version,
            published_version=published_version,
            reason="source and last-published versions match",
        )

    return ReleaseState(
        ready=False,
        source_version=source_version,
        published_version=published_version,
        reason=(
            "release-please is paused because the source version differs from its "
            "last-published manifest; complete and verify the bootstrap release, then "
            "reconcile the manifest before enabling automation, otherwise the release PR "
            "can propose a version downgrade"
        ),
    )


def _write_github_output(path: Path, state: ReleaseState) -> None:
    path.write_text(
        "\n".join(
            (
                f"ready={str(state.ready).lower()}",
                f"source-version={state.source_version}",
                f"published-version={state.published_version}",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)

    state = check_state(args.root.resolve())
    if args.github_output is not None:
        _write_github_output(args.github_output, state)

    prefix = "OK" if state.ready else "WARNING"
    print(
        f"{prefix}: Python source={state.source_version}; "
        f"release manifest={state.published_version}; {state.reason}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
