#!/usr/bin/env python3
"""Verify immutable GitHub Action pins and their maintenance-ledger inventory.

Every remote action must use a 40-character commit SHA, every use of one action
must share one SHA, and the contract ledger must name every action. The ledger
names actions without their SHAs: the workflows are the only record of a pin,
so a Dependabot SHA update needs no ledger edit (#1363).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

_USES_RE = re.compile(r"\buses:\s*([^\s#]+)")
_IMMUTABLE_ACTION_RE = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-f]{40}$")
_LEDGER_ACTION_RE = re.compile(r"`(?P<name>[^`/@\s]+/[^`@\s]+)@(?P<sha>[0-9a-f]{40})`")


def collect_workflow_actions(repo_root: Path) -> tuple[set[str], list[str]]:
    """Return remote workflow actions and any mutable-reference findings."""
    actions: set[str] = set()
    issues: list[str] = []
    workflow_root = repo_root / ".github" / "workflows"
    for pattern in ("*.yml", "*.yaml"):
        for workflow in sorted(workflow_root.glob(pattern)):
            for line_number, line in enumerate(
                workflow.read_text(encoding="utf-8").splitlines(), start=1
            ):
                match = _USES_RE.search(line)
                if not match:
                    continue
                action = match.group(1).strip("'\"")
                if action.startswith("./"):
                    continue
                actions.add(action)
                if not _IMMUTABLE_ACTION_RE.fullmatch(action):
                    relative = workflow.relative_to(repo_root)
                    issues.append(
                        f"{relative}:{line_number}: {action} must use a 40-character commit SHA"
                    )
    return actions, issues


def check_ledger(repo_root: Path, ledger_path: Path) -> list[str]:
    """Report mutable refs, split pins, unlisted actions, and SHAs copied into the ledger."""
    actions, issues = collect_workflow_actions(repo_root)
    ledger = ledger_path.read_text(encoding="utf-8")
    pins_by_name: dict[str, set[str]] = {}
    for action in actions:
        name, _, ref = action.rpartition("@")
        pins_by_name.setdefault(name or action, set()).add(ref)
    for name, refs in sorted(pins_by_name.items()):
        if len(refs) > 1:
            issues.append(
                f"workflow action uses more than one ref: {name} ({', '.join(sorted(refs))})"
            )
        if f"`{name}`" not in ledger:
            issues.append(f"undocumented workflow action: {name}")
    issues.extend(
        f"ledger repeats a workflow pin: {match.group(0).strip('`')}; name the action only"
        for match in _LEDGER_ACTION_RE.finditer(ledger)
    )
    return issues


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root",
    )
    parser.add_argument(
        "--ledger",
        default="docs/maintenance/2026-07-01-contract-ledger.md",
        help="Ledger path relative to the repository root",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root).resolve()
    ledger_path = repo_root / args.ledger
    if not ledger_path.is_file():
        print(f"ERROR: contract ledger not found: {ledger_path}", file=sys.stderr)
        return 2
    issues = check_ledger(repo_root, ledger_path)
    if issues:
        print("Workflow pin contract issues:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    actions, _ = collect_workflow_actions(repo_root)
    print(f"OK: {len(actions)} immutable workflow actions are inventoried in the contract ledger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
