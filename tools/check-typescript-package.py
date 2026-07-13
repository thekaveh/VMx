#!/usr/bin/env python3
"""Verify the exact allowlisted contents of the TypeScript npm package."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ENTRIES = ("index", "notifications", "conformance")
FIXTURES = (
    "command-truthtable.json",
    "derived-properties.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)

REQUIRED_PATHS = {
    "README.md",
    "package.json",
    *(f"src/fixtures/{name}" for name in FIXTURES),
    *(
        f"dist/{entry}{suffix}"
        for entry in ENTRIES
        for suffix in (".js", ".js.map", ".cjs", ".cjs.map", ".d.ts", ".d.cts")
    ),
}

_ESM_CHUNK = re.compile(r"^dist/chunk-[A-Za-z0-9_-]+\.js(?:\.map)?$")
_CJS_CHUNK = re.compile(r"^dist/chunk-[A-Za-z0-9_-]+\.cjs(?:\.map)?$")
_DTS_CHUNK = re.compile(r"^dist/relayCommand-[A-Za-z0-9_-]+\.d\.(?:ts|cts)$")


def _has_pair(paths: set[str], suffix: str, mate_suffix: str) -> bool:
    return any(
        path.endswith(suffix) and path[: -len(suffix)] + mate_suffix in paths for path in paths
    )


def validate_paths(paths: set[str]) -> list[str]:
    """Return deterministic allowlist errors for npm package paths."""
    errors = [f"missing required package file: {path}" for path in sorted(REQUIRED_PATHS - paths)]

    allowed = REQUIRED_PATHS | {
        path
        for path in paths
        if _ESM_CHUNK.fullmatch(path) or _CJS_CHUNK.fullmatch(path) or _DTS_CHUNK.fullmatch(path)
    }
    errors.extend(f"unexpected package file: {path}" for path in sorted(paths - allowed))

    esm = {path for path in paths if _ESM_CHUNK.fullmatch(path)}
    cjs = {path for path in paths if _CJS_CHUNK.fullmatch(path)}
    dts = {path for path in paths if _DTS_CHUNK.fullmatch(path)}
    if not _has_pair(esm, ".js", ".js.map"):
        errors.append("missing generated ESM chunk and source map")
    if not _has_pair(cjs, ".cjs", ".cjs.map"):
        errors.append("missing generated CommonJS chunk and source map")
    if not _has_pair(dts, ".d.ts", ".d.cts"):
        errors.append("missing generated declaration chunk pair")
    return errors


def package_paths(package_dir: Path) -> set[str]:
    """Run npm's real dry-run pack and return the included file paths."""
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=package_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    json_start = result.stdout.find("[")
    if json_start < 0:
        raise ValueError("npm pack did not emit a JSON array")
    payload = json.loads(result.stdout[json_start:])
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("npm pack JSON must contain exactly one package")
    package = payload[0]
    if not isinstance(package, dict) or not isinstance(package.get("files"), list):
        raise ValueError("npm pack JSON has no files array")
    paths = {
        item["path"]
        for item in package["files"]
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if len(paths) != len(package["files"]):
        raise ValueError("npm pack files contain invalid or duplicate paths")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "langs" / "typescript",
    )
    args = parser.parse_args(argv)

    try:
        paths = package_paths(args.package_dir.resolve())
        errors = validate_paths(paths)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: unable to inspect npm package: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: TypeScript npm package contains {len(paths)} allowlisted files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
