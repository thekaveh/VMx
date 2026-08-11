#!/usr/bin/env python3
"""Fail closed when the official React adapter npm payload drifts."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "react"
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


def main() -> int:
    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "@thekaveh/vmx-react":
        raise SystemExit("unexpected React adapter package name")
    peers = manifest.get("peerDependencies", {})
    for dependency in ("@thekaveh/vmx", "react", "rxjs", "use-sync-external-store"):
        if dependency not in peers:
            raise SystemExit(f"missing peer dependency: {dependency}")

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
        files = {f"package/{item['path']}" for item in payload[0]["files"]}
        missing = sorted(REQUIRED - files)
        if missing:
            raise SystemExit(f"React adapter payload is missing: {', '.join(missing)}")
        forbidden = sorted(path for path in files if "/tests/" in path or "/src/" in path)
        if forbidden:
            raise SystemExit(f"React adapter payload leaks source/tests: {', '.join(forbidden)}")

    print("OK: React adapter package metadata and payload are complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
