#!/usr/bin/env python3
"""Relabel merged Python release PRs, and report one left at `autorelease: pending`.

release-please creates no Python GitHub Release (`skip-github-release: true`),
so it never moves a merged release PR from `autorelease: pending` to
`autorelease: tagged`. While a merged release PR keeps the pending label,
release-please opens no new release PR (#1447).

- `relabel --version X.Y.Z` runs in release.yml after the `python-vX.Y.Z`
  GitHub Release exists. It relabels the merged release PR for that version.
- `check` runs in release-please.yml. It fails and names the PR when a merged
  release PR keeps the pending label after its GitHub Release exists. A PR
  whose tag or GitHub Release does not exist yet passes: the release is still
  in progress.

Both commands call the GitHub REST API through the `gh` CLI with `GH_TOKEN`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

PENDING = "autorelease: pending"
TAGGED = "autorelease: tagged"
RELEASE_PR_HEAD = "release-please--branches--main--components--python"
TAG_PREFIX = "python-v"
_COMPONENT = r"(?:0|[1-9][0-9]*)"
_TITLE_RE = re.compile(
    rf"chore\(main\): release python ({_COMPONENT}\.{_COMPONENT}\.{_COMPONENT})", re.ASCII
)


@dataclass(frozen=True)
class ReleasePr:
    """A merged Python release PR and the labels it carries."""

    number: int
    version: str | None
    labels: frozenset[str]


class LabelWriter(Protocol):
    """The label calls relabel makes, so tests can record them."""

    def remove_label(self, number: int, label: str) -> None: ...

    def add_label(self, number: int, label: str) -> None: ...


class GitHub:
    """The few GitHub REST calls the commands need, through the `gh` CLI."""

    def __init__(self, repository: str) -> None:
        self.repository = repository

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["gh", "api", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def merged_release_prs(self) -> list[ReleasePr]:
        """Return the merged PRs from the Python release-please branch."""
        owner = self.repository.split("/", 1)[0]
        result = self._run(
            "--method",
            "GET",
            "--paginate",
            "--slurp",
            f"repos/{self.repository}/pulls",
            "-f",
            "state=closed",
            "-f",
            "base=main",
            "-f",
            f"head={owner}:{RELEASE_PR_HEAD}",
            "-f",
            "per_page=100",
        )
        if result.returncode != 0:
            raise RuntimeError(f"unable to list release PRs: {result.stderr.strip()}")
        pages = json.loads(result.stdout)
        return parse_release_prs(pull for page in pages for pull in page)

    def exists(self, path: str) -> bool:
        """Return whether a GET of the path succeeds; a 404 means it does not exist."""
        result = self._run("--method", "GET", f"repos/{self.repository}/{path}")
        if result.returncode == 0:
            return True
        if "HTTP 404" in result.stderr:
            return False
        raise RuntimeError(f"unable to read {path}: {result.stderr.strip()}")

    def tag_exists(self, tag: str) -> bool:
        return self.exists(f"git/ref/tags/{urllib.parse.quote(tag, safe='')}")

    def release_exists(self, tag: str) -> bool:
        return self.exists(f"releases/tags/{urllib.parse.quote(tag, safe='')}")

    def remove_label(self, number: int, label: str) -> None:
        name = urllib.parse.quote(label, safe="")
        result = self._run(
            "--method", "DELETE", f"repos/{self.repository}/issues/{number}/labels/{name}"
        )
        if result.returncode != 0 and "HTTP 404" not in result.stderr:
            raise RuntimeError(f"unable to remove {label!r} from #{number}: {result.stderr}")

    def add_label(self, number: int, label: str) -> None:
        result = self._run(
            "--method",
            "POST",
            f"repos/{self.repository}/issues/{number}/labels",
            "-f",
            f"labels[]={label}",
        )
        if result.returncode != 0:
            raise RuntimeError(f"unable to add {label!r} to #{number}: {result.stderr}")


def parse_release_prs(pulls: Iterable[dict[str, object]]) -> list[ReleasePr]:
    """Keep merged PRs and read the release version from each title."""
    prs: list[ReleasePr] = []
    for pull in pulls:
        if not pull.get("merged_at"):
            continue
        match = _TITLE_RE.fullmatch(str(pull.get("title", "")))
        labels = pull.get("labels")
        names = frozenset(
            str(label.get("name", ""))
            for label in (labels if isinstance(labels, list) else [])
            if isinstance(label, dict)
        )
        number = pull.get("number")
        if not isinstance(number, int):
            continue
        prs.append(ReleasePr(number, match.group(1) if match else None, names))
    return sorted(prs, key=lambda pr: pr.number)


def pending_state(
    pr: ReleasePr,
    tag_exists: Callable[[str], bool],
    release_exists: Callable[[str], bool],
) -> str:
    """Classify a pending PR: 'no-tag', 'tag-without-release' or 'released'."""
    if pr.version is None:
        return "no-tag"
    tag = f"{TAG_PREFIX}{pr.version}"
    if not tag_exists(tag):
        return "no-tag"
    if not release_exists(tag):
        return "tag-without-release"
    return "released"


def check(
    prs: Sequence[ReleasePr],
    tag_exists: Callable[[str], bool],
    release_exists: Callable[[str], bool],
) -> list[str]:
    """Return one error per merged PR that keeps the pending label after its release."""
    errors: list[str] = []
    for pr in prs:
        if PENDING not in pr.labels:
            continue
        state = pending_state(pr, tag_exists, release_exists)
        if state == "released":
            errors.append(
                f"#{pr.number} keeps {PENDING!r} although the GitHub Release "
                f"{TAG_PREFIX}{pr.version} exists; release-please opens no new release PR "
                "until it is relabelled (see langs/python/RELEASING.md §2.1 step 10)"
            )
        else:
            print(f"OK: #{pr.number} keeps {PENDING!r}; release in progress ({state}).")
    return errors


def relabel(prs: Sequence[ReleasePr], version: str, github: LabelWriter) -> list[int]:
    """Move each merged release PR for the version to the tagged label."""
    changed: list[int] = []
    for pr in prs:
        if pr.version != version:
            continue
        if PENDING in pr.labels:
            github.remove_label(pr.number, PENDING)
        if TAGGED not in pr.labels:
            github.add_label(pr.number, TAGGED)
        changed.append(pr.number)
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="fail on a merged release PR left pending")
    relabel_parser = commands.add_parser("relabel", help="mark the release PR as tagged")
    relabel_parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")

    github = GitHub(args.repository)
    try:
        prs = github.merged_release_prs()
        if args.command == "check":
            errors = check(prs, github.tag_exists, github.release_exists)
            for error in errors:
                print(f"::error::{error}")
            if errors:
                return 1
            print("OK: no merged Python release PR is left at autorelease: pending.")
            return 0
        changed = relabel(prs, args.version, github)
    except RuntimeError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    if changed:
        numbers = ", ".join(f"#{number}" for number in changed)
        print(f"OK: {numbers} labelled {TAGGED!r}.")
    else:
        # A manual tag release (RELEASING.md §2.2) has no release PR.
        print(f"No merged release PR for python {args.version}; nothing to relabel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
