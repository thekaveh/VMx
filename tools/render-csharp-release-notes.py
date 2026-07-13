#!/usr/bin/env python3
"""Render C# GitHub Release notes from a selected-package manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _section(changelog: str, key: str) -> str | None:
    pattern = re.compile(
        rf"^## \[{re.escape(key)}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    return match.group("body").strip() if match else None


def render_notes(changelog: str, packages: list[dict[str, str]]) -> str:
    """Render matching core or package-qualified changelog sections."""
    rendered: list[str] = []
    for package in packages:
        package_id = package["id"]
        version = package["version"]
        key = version if package_id == "VMx" else f"{package_id} {version}"
        body = _section(changelog, key)
        if not body:
            raise ValueError(f"no C# changelog section found for {key}")
        rendered.append(f"## {package_id} {version}\n\n{body}\n")
    return "\n".join(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, list) or not all(isinstance(item, dict) for item in manifest):
            raise ValueError("release manifest must be a JSON object array")
        output = render_notes(args.changelog.read_text(encoding="utf-8"), manifest)
        args.output.write_text(output, encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: unable to render C# release notes: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
