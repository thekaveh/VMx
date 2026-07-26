#!/usr/bin/env python3
"""Assert TypeScript's tracked conformance schema copies match the spec."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return Path(out.stdout.strip())


_SYNC_DIRECTORIES: tuple[tuple[str, str], ...] = (
    ("spec/schemas", "langs/typescript/src/conformance/schemas"),
)


def _json_inventory(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    return {path.name: path for path in directory.iterdir() if path.suffix == ".json"}


def _tracked_json_names(root: Path, directory: str) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", f"{directory}/*.json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return {Path(line).name for line in out.stdout.splitlines() if line}


def main() -> int:
    try:
        root = repo_root()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: unable to locate repository root: {error}", file=sys.stderr)
        return 2

    failed = False
    for source_rel, copy_rel in _SYNC_DIRECTORIES:
        sources = _json_inventory(root / source_rel)
        copies = _json_inventory(root / copy_rel)
        try:
            tracked = _tracked_json_names(root, copy_rel)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            print(f"ERROR: unable to inspect tracked TypeScript copies: {error}", file=sys.stderr)
            return 2
        missing = sorted(sources.keys() - copies.keys())
        extra = sorted(copies.keys() - sources.keys())
        untracked = sorted(sources.keys() - tracked)
        for name in missing:
            print(f"FAIL: missing TypeScript tracked copy: {copy_rel}/{name}", file=sys.stderr)
            failed = True
        for name in extra:
            print(f"FAIL: unexpected TypeScript tracked copy: {copy_rel}/{name}", file=sys.stderr)
            failed = True
        for name in untracked:
            print(
                f"FAIL: TypeScript schema copy is not tracked: {copy_rel}/{name}", file=sys.stderr
            )
            failed = True
        for name in sorted(sources.keys() & copies.keys()):
            if sources[name].read_bytes() != copies[name].read_bytes():
                print(
                    f"FAIL: TypeScript tracked copy drifted from {source_rel}/{name}\n"
                    f"  source: {sources[name]}\n  copy:   {copies[name]}\n"
                    "  Re-sync: npm --prefix langs/typescript run sync-fixtures",
                    file=sys.stderr,
                )
                failed = True
                continue
            print(f"OK: {copy_rel}/{name} matches {source_rel}/{name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
