#!/usr/bin/env python3
"""Verify the React adapter manifest and the exact allowlisted npm payload."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "react"
PACKAGE_NAME = "@thekaveh/vmx-react"
PEER_DEPENDENCIES = ("@thekaveh/vmx", "react", "rxjs", "use-sync-external-store")
REQUIRED = {
    "package/package.json",
    "package/README.md",
    "package/LICENSE",
    "package/NOTICE",
    "package/dist/index.js",
    "package/dist/index.cjs",
    "package/dist/index.d.ts",
    "package/dist/index.d.cts",
}


def validate_manifest(manifest: dict) -> list[str]:
    """Return errors for the adapter package name and its peer dependencies."""
    errors = []
    if manifest.get("name") != PACKAGE_NAME:
        errors.append("unexpected React adapter package name")
    peers = manifest.get("peerDependencies", {})
    errors.extend(
        f"missing peer dependency: {dependency}"
        for dependency in PEER_DEPENDENCIES
        if dependency not in peers
    )
    return errors


def validate_paths(paths: set[str]) -> list[str]:
    """Return sorted errors when the packed payload differs from the allowlist."""
    errors = [f"missing required package file: {path}" for path in sorted(REQUIRED - paths)]
    errors.extend(f"unexpected package file: {path}" for path in sorted(paths - REQUIRED))
    return errors


def package_contents() -> set[str]:
    """Pack the adapter without lifecycle scripts and return the prefixed payload paths."""
    with tempfile.TemporaryDirectory(prefix="vmx-react-pack-") as directory:
        result = subprocess.run(
            ["npm", "pack", "--json", "--ignore-scripts", "--pack-destination", directory],
            cwd=PACKAGE,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "npm_config_cache": str(Path(directory) / ".npm-cache")},
            timeout=180,
        )
    payload = json.loads(result.stdout)
    return {f"package/{item['path']}" for item in payload[0]["files"]}


def main() -> int:
    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    errors = validate_manifest(manifest) + validate_paths(package_contents())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("OK: React adapter package metadata and payload are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
