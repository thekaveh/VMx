#!/usr/bin/env python3
"""Select exactly one C# package from a package-specific stable release tag."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

TAG_TARGETS: tuple[tuple[str, str], ...] = (
    ("csharp-v", "VMx"),
    ("csharp-notifications-v", "VMx.Notifications"),
    ("csharp-dependency-injection-v", "VMx.Extensions.DependencyInjection"),
)
_STABLE_VERSION = r"([0-9]+\.[0-9]+\.[0-9]+)"


def parse_tag(tag: str) -> tuple[str, str]:
    """Return the one package ID and stable version encoded by *tag*."""
    for prefix, package_id in TAG_TARGETS:
        match = re.fullmatch(re.escape(prefix) + _STABLE_VERSION, tag)
        if match is not None:
            return package_id, match.group(1)
    raise ValueError(f"unknown or non-stable C# release tag: {tag}")


def build_manifest(tag: str, project_root: Path) -> list[dict[str, str]]:
    """Build a single-entry artifact manifest after exact project validation."""
    package_id, version = parse_tag(tag)
    matches: list[tuple[Path, str]] = []
    for project in sorted(project_root.glob("*/*.csproj")):
        root = ET.parse(project).getroot()
        if root.findtext("PropertyGroup/PackageId") == package_id:
            matches.append((project, root.findtext("PropertyGroup/Version") or ""))

    if len(matches) != 1:
        raise ValueError(
            f"release tag {tag} maps to {package_id}, but found {len(matches)} matching projects"
        )
    project, project_version = matches[0]
    if project_version != version:
        raise ValueError(
            f"release tag {tag} requires {package_id} {version}, but {project} declares "
            f"{project_version or '<missing>'}"
        )

    return [
        {
            "id": package_id,
            "version": version,
            "nupkg": f"{package_id}.{version}.nupkg",
            "snupkg": f"{package_id}.{version}.snupkg",
        }
    ]


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--project-root", type=Path, default=repo / "langs" / "csharp" / "src")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        manifest = build_manifest(args.tag, args.project_root)
    except (ValueError, ET.ParseError) as error:
        parser.error(str(error))
    rendered = json.dumps(manifest, indent=2) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
