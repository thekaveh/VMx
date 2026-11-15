#!/usr/bin/env python3
"""Enforce the spec-discipline ADR rule for one pull request.

A spec text change needs a numbered ADR in the same pull request. The workflow
passes the base and head commits of the event, and the script diffs from their
merge base. The base branch can move after the pull request branches, and a diff
from the base tip would count those later base changes as the pull request's.

Standard library only: the spec-discipline job runs this on the runner's
python3 without installing uv.
"""

import argparse
import json
import os
import re
import subprocess
import sys

BYPASS_LABEL = "no-adr-needed"
GIT_TIMEOUT_SECONDS = 60

# A numbered ADR file: spec/ADRs/NNNN-kebab-title.md. Titles may contain dots,
# as in 0020-v2.0-spec-text-refresh.md. README.md and notes do not match.
NUMBERED_ADR = re.compile(r"spec/ADRs/[0-9]{4}-[^/]+\.md")

# Spec files that never need a paired ADR (see spec/ADRs/README.md and
# CONTRIBUTING.md section 3). Exact paths for single files, prefixes for trees.
EXEMPT_SPEC_FILES = frozenset(
    {
        "spec/README.md",
        "spec/HISTORY.md",
        "spec/VERSION",
        "spec/12-conformance.md",
    }
)
EXEMPT_SPEC_PREFIXES = ("spec/ADRs/", "spec/fixtures/", "spec/proposals/")


def is_exempt(path: str) -> bool:
    return path in EXEMPT_SPEC_FILES or path.startswith(EXEMPT_SPEC_PREFIXES)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    ).stdout


def merge_base(base_sha: str, head_sha: str) -> str | None:
    """The newest commit that both sides share, or None when they share none."""
    result = subprocess.run(
        ["git", "merge-base", base_sha, head_sha],
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    found = result.stdout.strip()
    return found if result.returncode == 0 and found else None


def changed_spec_files(diff_base: str, head_sha: str) -> list[str]:
    names = git("diff", "--name-only", diff_base, head_sha, "--", "spec/").splitlines()
    return [name for name in names if not is_exempt(name)]


def added_adrs(diff_base: str, head_sha: str) -> list[str]:
    added = git(
        "diff", "--name-only", "--diff-filter=A", diff_base, head_sha, "--", "spec/ADRs/"
    ).splitlines()
    return [path for path in added if NUMBERED_ADR.fullmatch(path)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)

    labels = json.loads(os.environ.get("PR_LABELS_JSON", "[]"))
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        print("::error::PR_LABELS_JSON must be a JSON array of label names.")
        return 1

    diff_base = merge_base(args.base_sha, args.head_sha)
    if diff_base is None:
        print(f"::error::No merge base between {args.base_sha} and {args.head_sha}.")
        return 1

    changed = changed_spec_files(diff_base, args.head_sha)
    new_adrs = added_adrs(diff_base, args.head_sha)

    if not changed:
        print("OK: no spec text changed on this pull request.")
        return 0
    if new_adrs:
        print("OK: spec changes include a new ADR:")
        print("\n".join(new_adrs))
        return 0
    if BYPASS_LABEL in labels:
        print(f"::notice::Spec changed without an ADR, but bypassed by '{BYPASS_LABEL}' label.")
        print("Changed spec files (bypassed):")
        print("\n".join(changed))
        return 0

    print("::error::Spec text changed but no new ADR was added in spec/ADRs/.")
    print("Changed spec files:")
    print("\n".join(changed))
    print()
    print("If this change does not warrant an ADR (e.g., it is a typo or pure formatting),")
    print("the maintainer may add the label 'no-adr-needed' to bypass this check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
