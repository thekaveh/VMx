#!/usr/bin/env python3
"""Verify that the Rust crate package holds exactly the expected files.

The expected inventory is the fixed top-level and Cargo-generated files plus
every file that Git tracks under ``langs/rust/src`` and ``langs/rust/tests``.
A new tracked source or test file therefore needs no edit here. A packaged
file outside that inventory, such as ``.env`` or an untracked scratch test,
fails the check.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "langs" / "rust"

# The top-level files that `include` in Cargo.toml selects, and the files
# that `cargo package` generates.
FIXED_PATHS = frozenset(
    {
        ".cargo_vcs_info.json",
        "CHANGELOG.md",
        "Cargo.lock",
        "Cargo.toml",
        "Cargo.toml.orig",
        "LICENSE",
        "NOTICE",
        "README.md",
    }
)

# The crate directories whose tracked files `include` selects.
SOURCE_DIRS = ("src", "tests")


def tracked_source_paths(package_dir: Path) -> set[str]:
    """Return the crate-relative paths that Git tracks in ``SOURCE_DIRS``."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *SOURCE_DIRS],
        cwd=package_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {path for path in result.stdout.split("\0") if path}


def expected_paths(tracked: set[str]) -> frozenset[str]:
    """Return the full expected package inventory for ``tracked`` sources."""
    return FIXED_PATHS | frozenset(tracked)


def validate_paths(paths: set[str], tracked: set[str]) -> list[str]:
    """Return deterministic errors for missing or unexpected package paths."""
    expected = expected_paths(tracked)
    errors = [f"missing required package file: {path}" for path in sorted(expected - paths)]
    for path in sorted(paths - expected):
        if path.split("/", 1)[0] in SOURCE_DIRS:
            reason = "Git does not track it"
        else:
            reason = "it is not a fixed top-level or generated crate file"
        errors.append(f"unexpected package file: {path} ({reason})")
    return errors


def package_paths(package_dir: Path) -> set[str]:
    """Run Cargo's real package listing and return every included path."""
    result = subprocess.run(
        [
            "cargo",
            "package",
            "--manifest-path",
            str(package_dir / "Cargo.toml"),
            "--locked",
            "--list",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(paths) != len(set(paths)):
        raise ValueError("cargo package listed duplicate paths")
    return set(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=DEFAULT_PACKAGE_DIR,
    )
    args = parser.parse_args(argv)

    try:
        package_dir = args.package_dir.resolve()
        paths = package_paths(package_dir)
        tracked = tracked_source_paths(package_dir)
        if not tracked:
            raise ValueError(f"Git tracks no files under src/ or tests/ in {package_dir}")
        errors = validate_paths(paths, tracked)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"ERROR: unable to inspect Rust crate package: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"OK: Rust crate package contains {len(paths)} files: "
        f"{len(FIXED_PATHS)} fixed and {len(tracked)} tracked under src/ and tests/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
