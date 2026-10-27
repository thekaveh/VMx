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
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

REPO_URL = "https://github.com/thekaveh/VMx"
FRAMEWORKS = {"net8.0", ".NETStandard2.0"}
_CORE_PROPERTIES = re.compile(
    r"^package/services/metadata/core-properties/(?:[0-9a-f]+|nuget)\.psmdcp$"
)
_CORE_DEPENDENCIES = {
    "net8.0": [("System.Reactive", "7.0.0")],
    ".NETStandard2.0": [
        ("Microsoft.Bcl.AsyncInterfaces", "10.0.13"),
        ("System.Collections.Immutable", "10.0.13"),
        ("System.Reactive", "7.0.0"),
        ("System.Text.Json", "10.0.13"),
    ],
}
_PACKAGE_DEPENDENCIES = {
    "VMx": _CORE_DEPENDENCIES,
    "VMx.Notifications": _CORE_DEPENDENCIES,
    "VMx.Extensions.DependencyInjection": {
        framework: [
            ("Microsoft.Extensions.DependencyInjection.Abstractions", "10.0.13"),
            *dependencies,
        ]
        for framework, dependencies in _CORE_DEPENDENCIES.items()
    },
}


# A .nupkg carries none of the repository's files, so every README link and
# image must be absolute. NuGet renders images only from trusted hosts and
# formats; VMx keeps its package READMEs to one host and raster formats.
README_IMAGE_HOSTS = {"raw.githubusercontent.com"}
README_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")
_FENCED_CODE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HTML_TARGET = re.compile(
    r"""<(img|a|source)\b[^>]*?\b(?:src|href|srcset)\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
# An optional "...", '...' or (...) title after an inline destination (CommonMark).
_TITLE = re.compile(r"""\s+(?:"[^"]*"|'[^']*'|\([^)]*\))""")
_REFERENCE_LABEL = re.compile(r"\[([^\]]*)\]")
# The destination may follow on the next line (CommonMark).
_REFERENCE_DEFINITION = re.compile(
    r"^ {0,3}\[([^\]]+)\]:[ \t]*(?:\n[ \t]*)?<?([^\s>]+)>?.*$", re.MULTILINE
)


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _closing_bracket(text: str, start: int) -> int:
    """Return the index of the ']' that closes the '[' at start, or -1."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _destination(text: str, start: int) -> tuple[str, int] | None:
    """Parse an inline destination and optional title at text[start] == '('.

    Return the URL and the index after the closing ')', or None. A bare
    destination may hold balanced parentheses at any depth (CommonMark).
    """
    if start >= len(text) or text[start] != "(":
        return None
    index = start + 1
    while index < len(text) and text[index] in " \t\n":
        index += 1
    if index < len(text) and text[index] == "<":
        close = text.find(">", index)
        if close < 0 or "\n" in text[index:close]:
            return None
        url, index = text[index + 1 : close], close + 1
    else:
        begin, depth = index, 0
        while index < len(text) and not text[index].isspace():
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            index += 1
        url = text[begin:index]
        if depth or not url:
            return None
    title = _TITLE.match(text, index)
    if title:
        index = title.end()
    while index < len(text) and text[index] in " \t\n":
        index += 1
    if index < len(text) and text[index] == ")":
        return url, index + 1
    return None


def _inline_targets(
    text: str, definitions: dict[str, str], uses: dict[str, set[bool]]
) -> list[tuple[bool, str]]:
    """Return (is_image, url) for inline links and images, including the image
    inside a linked image. Record which reference definitions are used, and how."""
    targets: list[tuple[bool, str]] = []
    index = 0
    while (start := text.find("[", index)) >= 0:
        if start > 0 and text[start - 1] == "\\":
            index = start + 1
            continue
        end = _closing_bracket(text, start)
        if end < 0:
            # An unmatched '[' is prose; later links still count.
            index = start + 1
            continue
        is_image = start > 0 and text[start - 1] == "!"
        inner = text[start + 1 : end]
        destination = _destination(text, end + 1)
        reference = _REFERENCE_LABEL.match(text, end + 1)
        label = _label(reference.group(1) or inner) if reference else _label(inner)
        if destination:
            url, index = destination
            targets.append((is_image, url))
        elif label in definitions:
            uses.setdefault(label, set()).add(is_image)
            index = reference.end() if reference else end + 1
        else:
            index = start + 1
            continue
        targets += _inline_targets(inner, definitions, uses)
    return targets


def validate_readme(text: str, package_id: str) -> list[str]:
    """Return errors for a packaged README that would not render outside the repository."""
    errors: list[str] = []
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line != f"# {package_id}":
        errors.append(f"README must open with the heading '# {package_id}'")
    prose = _INLINE_CODE.sub("", _FENCED_CODE.sub("", text))
    definitions = {
        _label(label): url for label, url in reversed(_REFERENCE_DEFINITION.findall(prose))
    }
    uses: dict[str, set[bool]] = {}
    targets = _inline_targets(_REFERENCE_DEFINITION.sub("", prose), definitions, uses)
    targets += [(tag.lower() != "a", url) for tag, url in _HTML_TARGET.findall(prose)]
    # A definition gets the rules of each way it is used; an unused one is a link.
    targets += [
        (is_image, url)
        for label, url in definitions.items()
        for is_image in sorted(uses.get(label, {False}))
    ]
    for is_image, url in targets:
        kind = "image" if is_image else "link"
        if url.startswith("#") and not is_image:
            continue
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            errors.append(f"README {kind} must be an absolute https URL: {url}")
            continue
        if is_image and parts.netloc not in README_IMAGE_HOSTS:
            errors.append(f"README image host is not allowed: {url}")
        elif is_image and not parts.path.lower().endswith(README_IMAGE_SUFFIXES):
            errors.append(f"README image must be PNG, JPEG, or GIF: {url}")
    return errors


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
                if not symbols and "README.md" in paths:
                    try:
                        readme = package.read("README.md").decode("utf-8")
                    except UnicodeDecodeError:
                        errors.append(f"{archive.name}: README.md is not UTF-8")
                    else:
                        for error in validate_readme(readme, package_id):
                            errors.append(f"{archive.name}: {error}")
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
