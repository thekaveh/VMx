#!/usr/bin/env python3
"""Verify that VMx's root and nested SwiftPM manifests stay equivalent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from copy import deepcopy
from difflib import unified_diff
from pathlib import Path

ROOT_TARGET_PREFIX = "langs/swift/"


def normalize_dump(
    payload: dict[str, object],
    *,
    root_prefix: str,
) -> dict[str, object]:
    """Return a copied package dump with the root target prefix removed."""
    normalized = deepcopy(payload)
    package_kind = normalized.get("packageKind")
    if isinstance(package_kind, dict):
        roots = package_kind.get("root")
        if isinstance(roots, list):
            package_kind["root"] = ["<package-root>" for _ in roots]

    targets = normalized.get("targets")
    if not isinstance(targets, list):
        raise ValueError("Swift package dump has no targets array")

    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("Swift package dump contains a non-object target")
        path = target.get("path")
        if root_prefix and isinstance(path, str) and path.startswith(root_prefix):
            target["path"] = path.removeprefix(root_prefix)
    return normalized


def manifest_diff(
    root_payload: dict[str, object],
    nested_payload: dict[str, object],
) -> str:
    """Return a unified structural diff, or an empty string when equivalent."""
    root = normalize_dump(root_payload, root_prefix=ROOT_TARGET_PREFIX)
    nested = normalize_dump(nested_payload, root_prefix="")
    root_lines = json.dumps(root, indent=2, sort_keys=True).splitlines()
    nested_lines = json.dumps(nested, indent=2, sort_keys=True).splitlines()
    return "\n".join(
        unified_diff(
            root_lines,
            nested_lines,
            fromfile="root/Package.swift",
            tofile="langs/swift/Package.swift",
            lineterm="",
        )
    )


def dump_package(repo_root: Path, package_path: Path) -> dict[str, object]:
    """Run SwiftPM's manifest evaluator and return its JSON package dump."""
    result = subprocess.run(
        [
            "swift",
            "package",
            "dump-package",
            "--package-path",
            str(package_path),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Swift package dump is not a JSON object")
    return payload


def check(repo_root: Path) -> str:
    """Evaluate both manifests and return their normalized structural diff."""
    root = dump_package(repo_root, Path("."))
    nested = dump_package(repo_root, Path("langs/swift"))
    return manifest_diff(root, nested)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)

    try:
        diff = check(args.repo_root.resolve())
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: unable to compare SwiftPM manifests: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        return 2

    if diff:
        print("ERROR: root and nested SwiftPM manifests differ:", file=sys.stderr)
        print(diff, file=sys.stderr)
        return 1

    print("OK: root and nested SwiftPM manifests are structurally equivalent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
