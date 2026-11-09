#!/usr/bin/env python3
"""Check that the Rust API baseline revision carries the version of the pull request's base.

``cargo semver-checks`` accepts any break when the ``Cargo.toml`` version has
moved past the version at the baseline revision; at 0.x a minor bump allows a
break. A baseline revision with an older version than ``develop`` would thus
let every later break through. The rule: in a pull request, the
``langs/rust/Cargo.toml`` version at ``langs/rust/api/baseline-revision`` must
equal the version at the pull request's base commit. A pull request that bumps
the version therefore compares with the old version and may break the API; the
first pull request after it must move the baseline revision to a commit with
the new version, for example its own base commit (CONTRIBUTING.md §2.8,
#1365).

Usage (CI passes the pull request's base commit)::

    python3 tools/check-rust-api-baseline.py --base-rev <base commit>

Exit codes: 0 when the versions are equal, 1 when they differ, 2 when a
revision or version cannot be read.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "langs/rust/Cargo.toml"
BASELINE_FILE = "langs/rust/api/baseline-revision"
_VERSION = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')


class BaselineError(Exception):
    """A revision or its manifest version cannot be read."""


def manifest_version(root: Path, revision: str) -> str:
    """Return the ``Cargo.toml`` package version at ``revision``."""
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{MANIFEST}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise BaselineError(f"cannot read {MANIFEST} at {revision}: {completed.stderr.strip()}")
    match = _VERSION.search(completed.stdout)
    if match is None:
        raise BaselineError(f"{MANIFEST} at {revision} declares no version")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--base-rev", required=True, help="the pull request's base commit")
    args = parser.parse_args(argv)
    try:
        baseline = (args.root / BASELINE_FILE).read_text(encoding="utf-8").strip()
        baseline_version = manifest_version(args.root, baseline)
        base_version = manifest_version(args.root, args.base_rev)
    except (BaselineError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if baseline_version == base_version:
        print(
            f"OK: the baseline revision {baseline} and the base {args.base_rev} "
            f"both declare vmx-rs {base_version}"
        )
        return 0
    print(
        f"FAIL: the baseline revision {baseline} declares vmx-rs {baseline_version}, "
        f"but the base {args.base_rev} declares {base_version}. cargo-semver-checks "
        "would accept any break against that baseline. Set "
        f"{BASELINE_FILE} to a develop commit that declares {base_version}, for "
        f"example {args.base_rev} (CONTRIBUTING.md §2.8).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
