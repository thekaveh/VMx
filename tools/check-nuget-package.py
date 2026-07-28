#!/usr/bin/env python3
"""Validate VMx NuGet main and symbol packages against an exact contract."""

from __future__ import annotations

import argparse
import re
import stat
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from zipfile import BadZipFile, ZipFile

REPO_URL = "https://github.com/thekaveh/VMx"
FRAMEWORKS = {"net8.0", ".NETStandard2.0"}
_CORE_PROPERTIES = re.compile(r"^package/services/metadata/core-properties/[0-9a-f]+\.psmdcp$")
_CORE_DEPENDENCIES = {
    "net8.0": [("System.Reactive", "7.0.0")],
    ".NETStandard2.0": [
        ("Microsoft.Bcl.AsyncInterfaces", "10.0.10"),
        ("System.Collections.Immutable", "10.0.10"),
        ("System.Reactive", "7.0.0"),
        ("System.Text.Json", "10.0.10"),
    ],
}
_PACKAGE_DEPENDENCIES = {
    "VMx": _CORE_DEPENDENCIES,
    "VMx.Notifications": _CORE_DEPENDENCIES,
    "VMx.Extensions.DependencyInjection": {
        framework: [
            ("Microsoft.Extensions.DependencyInjection.Abstractions", "10.0.10"),
            *dependencies,
        ]
        for framework, dependencies in _CORE_DEPENDENCIES.items()
    },
}


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
                "LICENSE",
                "NOTICE",
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
        dependency_items = group.findall("{*}dependency")
        dependencies = [
            (item.get("id") or "", item.get("version") or "") for item in dependency_items
        ]
        framework = group.get("targetFramework", "")
        expected_dependencies = [
            *([] if vmx_floor is None else [("VMx", vmx_floor)]),
            *_PACKAGE_DEPENDENCIES.get(package_id, {}).get(framework, []),
        ]
        if sorted(dependencies) != sorted(expected_dependencies):
            errors.append(
                f"{framework} dependencies must be exactly "
                f"{sorted(expected_dependencies)}; found {sorted(dependencies)}"
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
                members = package.infolist()
                names = [member.filename for member in members]
                duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
                for name in duplicates:
                    errors.append(f"{archive.name}: duplicate package file: {name}")
                for member in members:
                    mode = member.external_attr >> 16
                    if member.create_system == 3 and stat.S_ISLNK(mode):
                        errors.append(
                            f"{archive.name}: symbolic links are forbidden: {member.filename}"
                        )
                core_properties = [name for name in names if _CORE_PROPERTIES.fullmatch(name)]
                if len(core_properties) != 1:
                    errors.append(
                        f"{archive.name}: expected exactly one core-properties metadata file"
                    )
                paths = set(names)
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
    discovered: dict[str, str] = {}
    for project in sorted(project_root.glob("*/*.csproj")):
        root = ET.parse(project).getroot()
        package_id = root.findtext("PropertyGroup/PackageId")
        version = root.findtext("PropertyGroup/Version")
        if package_id and version:
            discovered[package_id] = version
    core_version = discovered.get("VMx")
    return {
        package_id: (version, None if package_id == "VMx" else core_version)
        for package_id, version in discovered.items()
    }


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=repo / "langs" / "csharp" / "src")
    args = parser.parse_args(argv)
    expected = discover_expected(args.project_root)
    if not expected:
        print(
            f"ERROR: no packable projects discovered under {args.project_root}",
            file=sys.stderr,
        )
        return 1
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
