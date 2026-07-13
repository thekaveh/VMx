#!/usr/bin/env python3
"""Validate VMx NuGet main and symbol packages against an exact contract."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import BadZipFile, ZipFile

REPO_URL = "https://github.com/thekaveh/VMx"
FRAMEWORKS = {"net8.0", ".NETStandard2.0"}
_CORE_PROPERTIES = re.compile(r"^package/services/metadata/core-properties/[0-9a-f]+\.psmdcp$")


def expected_paths(package_id: str, *, symbols: bool) -> set[str]:
    """Return the exact stable archive paths, using a marker for generated metadata."""
    extension = "pdb" if symbols else "dll"
    paths = {
        "_rels/.rels",
        f"{package_id}.nuspec",
        f"lib/net8.0/{package_id}.{extension}",
        f"lib/netstandard2.0/{package_id}.{extension}",
        "[Content_Types].xml",
        "<core-properties>",
    }
    if not symbols:
        paths.update(
            {
                f"lib/net8.0/{package_id}.xml",
                f"lib/netstandard2.0/{package_id}.xml",
                "README.md",
            }
        )
    return paths


def _normalized_paths(paths: set[str]) -> set[str]:
    return {"<core-properties>" if _CORE_PROPERTIES.fullmatch(path) else path for path in paths}


def _text(parent: ET.Element, name: str) -> str | None:
    child = parent.find(f"{{*}}{name}")
    return child.text if child is not None else None


def _validate_nuspec(
    data: bytes,
    package_id: str,
    version: str,
    vmx_floor: str | None,
    *,
    symbols: bool,
) -> list[str]:
    root = ET.fromstring(data)
    metadata = root.find("{*}metadata")
    if metadata is None:
        return ["nuspec has no metadata"]
    errors: list[str] = []
    required = {
        "id": package_id,
        "version": version,
        "projectUrl": REPO_URL,
    }
    if symbols:
        package_type = metadata.find("{*}packageTypes/{*}packageType")
        if package_type is None or package_type.get("name") != "SymbolsPackage":
            errors.append("symbol nuspec must declare SymbolsPackage")
    else:
        required.update({"authors": "Kaveh Razavi", "license": "Apache-2.0", "readme": "README.md"})
    for name, expected in required.items():
        if _text(metadata, name) != expected:
            errors.append(f"nuspec {name} must be {expected!r}")
    repository = metadata.find("{*}repository")
    if repository is None or repository.get("url") != REPO_URL:
        errors.append("nuspec repository URL is missing or incorrect")
    elif not re.fullmatch(r"[0-9a-f]{40}", repository.get("commit", "")):
        errors.append("nuspec repository commit must be a full SHA")
    if not _text(metadata, "description") or not _text(metadata, "tags"):
        errors.append("nuspec description and tags are required")
    groups = metadata.findall("{*}dependencies/{*}group")
    if {group.get("targetFramework") for group in groups} != FRAMEWORKS:
        errors.append("nuspec dependency groups must be net8.0 and .NETStandard2.0")
    for group in groups:
        dependencies = {
            item.get("id"): item.get("version") for item in group.findall("{*}dependency")
        }
        if vmx_floor is None:
            if "VMx" in dependencies:
                errors.append("core package must not depend on itself")
        elif dependencies.get("VMx") != vmx_floor:
            errors.append(
                f"{group.get('targetFramework')} VMx dependency must be exactly {vmx_floor}"
            )
    return errors


def validate_package_pair(
    package_dir: Path, package_id: str, version: str, vmx_floor: str | None
) -> list[str]:
    """Return contract errors for one main/symbol package pair."""
    errors: list[str] = []
    for symbols, suffix in ((False, "nupkg"), (True, "snupkg")):
        archive = package_dir / f"{package_id}.{version}.{suffix}"
        if not archive.is_file():
            errors.append(f"missing package: {archive.name}")
            continue
        try:
            with ZipFile(archive) as package:
                paths = set(package.namelist())
                expected = expected_paths(package_id, symbols=symbols)
                normalized = _normalized_paths(paths)
                for path in sorted(expected - normalized):
                    errors.append(f"{archive.name}: missing package file: {path}")
                for path in sorted(normalized - expected):
                    errors.append(f"{archive.name}: unexpected package file: {path}")
                nuspec = f"{package_id}.nuspec"
                if nuspec in paths:
                    for error in _validate_nuspec(
                        package.read(nuspec),
                        package_id,
                        version,
                        vmx_floor,
                        symbols=symbols,
                    ):
                        errors.append(f"{archive.name}: {error}")
        except (BadZipFile, ET.ParseError) as error:
            errors.append(f"{archive.name}: cannot inspect package: {error}")
    return errors


def discover_expected(project_root: Path) -> dict[str, tuple[str, str | None]]:
    """Read package IDs/versions from C# source projects."""
    expected: dict[str, tuple[str, str | None]] = {}
    for project in sorted(project_root.glob("*/*.csproj")):
        root = ET.parse(project).getroot()
        package_id = root.findtext("PropertyGroup/PackageId")
        version = root.findtext("PropertyGroup/Version")
        if package_id and version:
            expected[package_id] = (version, None if package_id == "VMx" else "3.20.0")
    return expected


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=repo / "langs" / "csharp" / "src")
    args = parser.parse_args(argv)
    expected = discover_expected(args.project_root)
    errors = [
        error
        for package_id, (version, vmx_floor) in expected.items()
        for error in validate_package_pair(args.package_dir, package_id, version, vmx_floor)
    ]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: validated {len(expected)} NuGet package and symbol pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
