#!/usr/bin/env python3
"""Validate VMx NuGet main and symbol packages against an exact contract.

Each main package ships the README in ``langs/csharp/packaging/<package>/``.
The packaged README rules are:

- The README opens with the package's heading.
- It contains no raw HTML, because NuGet's Markdown renderer does not list HTML
  support. Code blocks, code spans, and link titles are not scanned.
- Every link and image is an absolute ``https`` URL. Every image is a PNG,
  JPEG, or GIF on ``raw.githubusercontent.com``.
- A ``github.com/thekaveh/VMx`` or ``www.github.com/thekaveh/VMx`` ``blob``,
  ``tree``, or ``raw`` URL, or a ``raw.githubusercontent.com/thekaveh/VMx``
  URL, on ``main``, ``HEAD``, or ``refs/heads/main`` names a path in the
  checked-out tree (``--repo-root``, by default this repository) after ``.``
  and ``..`` segments resolve. When that root is a Git work tree, the path is
  also tracked by Git.
- No such URL names a path above the repository root or a
  ``thekaveh/VMx.git/...`` path, which GitHub does not serve.
"""

from __future__ import annotations

import argparse
import bisect
import os
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

REPO_URL = "https://github.com/thekaveh/VMx"
REPO_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORKS = {"net8.0", ".NETStandard2.0"}
_CORE_PROPERTIES = re.compile(
    r"^package/services/metadata/core-properties/(?:[0-9a-f]+|nuget)\.psmdcp$"
)
CENTRAL_PACKAGES = REPO_ROOT / "langs" / "csharp" / "Directory.Packages.props"
# The dependency IDs of each framework group are the packaging contract. Their
# versions come from the central package file, so a Dependabot version update
# there needs no edit here (#1363).
_CORE_DEPENDENCY_IDS = {
    "net8.0": ["System.Reactive"],
    ".NETStandard2.0": [
        "Microsoft.Bcl.AsyncInterfaces",
        "System.Collections.Immutable",
        "System.Reactive",
        "System.Text.Json",
    ],
}
_PACKAGE_DEPENDENCY_IDS = {
    "VMx": _CORE_DEPENDENCY_IDS,
    "VMx.Notifications": _CORE_DEPENDENCY_IDS,
    "VMx.Extensions.DependencyInjection": {
        framework: ["Microsoft.Extensions.DependencyInjection.Abstractions", *ids]
        for framework, ids in _CORE_DEPENDENCY_IDS.items()
    },
}


def central_package_versions(props: Path = CENTRAL_PACKAGES) -> dict[str, str]:
    """Return the PackageVersion pins of a Directory.Packages.props file."""
    root = ET.parse(props).getroot()
    return {
        item.get("Include", ""): item.get("Version", "")
        for item in root.iter()
        if item.tag.rpartition("}")[2] == "PackageVersion"
    }


def package_dependencies(
    package_id: str, versions: dict[str, str] | None = None
) -> dict[str, list[tuple[str, str]]]:
    """Return the expected (ID, version) dependencies of each framework group."""
    versions = central_package_versions() if versions is None else versions
    return {
        framework: [(dependency, versions.get(dependency, "<not pinned>")) for dependency in ids]
        for framework, ids in _PACKAGE_DEPENDENCY_IDS.get(package_id, {}).items()
    }


# A .nupkg carries none of the repository's files, so every README link and
# image must be absolute. NuGet renders images only from trusted hosts and
# formats; VMx keeps its package READMEs to one host and raster formats.
README_IMAGE_HOSTS = {"raw.githubusercontent.com"}
README_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")
# CommonMark code forms. A fence may be indented up to three columns past the
# enclosing list content; an indented code block needs four (#1439).
_FENCE_OPEN = re.compile(r"^(?P<indent>[ ]*)(?P<fence>`{3,}(?=[^`]*$)|~{3,})")
_FENCE_CLOSE = re.compile(r"^(?P<indent>[ ]*)(?P<fence>`{3,}|~{3,})[ \t]*$")
_LIST_ITEM = re.compile(r"^(?P<marker>[ ]{0,3}(?:[-+*]|\d{1,9}[.)]))(?P<gap>[ ]{1,4}|$)")
_ATX_HEADING = re.compile(r"^[ ]{0,3}#{1,6}(?:[ \t]|$)")
_BACKTICKS = re.compile(r"`+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# nuget.org renders package READMEs with Markdig, and NuGet's list of supported
# Markdown features has no raw HTML. Match the CommonMark raw HTML forms: open
# and closing tags, comments, processing instructions, declarations and CDATA.
# An autolink such as <https://...> is not a tag, because ':' cannot follow a
# tag name.
_TAG_NAME = r"[A-Za-z][A-Za-z0-9-]*"
_ATTRIBUTE = r"""\s+[A-Za-z_:][A-Za-z0-9_.:-]*(?:\s*=\s*(?:[^\s"'=<>`]+|'[^']*'|"[^"]*"))?"""
_HTML_TAG = re.compile(rf"<(?:{_TAG_NAME}(?:{_ATTRIBUTE})*\s*/?>|/{_TAG_NAME}\s*>)")
# Constructs that run to a fixed closer. Each closer is searched for with
# str.find, and a closer that is absent after one opener is absent after every
# later opener, so the scan stays linear for unterminated openers (#1439).
_HTML_SPANS = (("<!--", "-->"), ("<![CDATA[", "]]>"), ("<?", "?>"))
_DECLARATION = re.compile(r"<![A-Za-z]")
# A CommonMark autolink; not the <...> form of an inline link destination.
_AUTOLINK = re.compile(r"(?<!\\)(?<!\]\()<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^\s<>]*)>")
# An optional "...", '...' or (...) title after an inline destination (CommonMark).
_TITLE = re.compile(r"""\s+(?:"[^"]*"|'[^']*'|\([^)]*\))""")
# The title may follow on the next line, and only spaces may follow it (CommonMark).
_DEFINITION_TITLE = re.compile(
    r"""^( {0,3}\[[^\]]+\]:[ \t]*(?:\n[ \t]*)?<?[^\s>]+>?)"""
    r"""(?:[ \t]+|[ \t]*\n[ \t]*)(?:"[^"]*"|'[^']*'|\([^)]*\))(?=[ \t]*$)""",
    re.MULTILINE,
)
_REFERENCE_LABEL = re.compile(r"\[([^\]]*)\]")
# The destination may follow on the next line (CommonMark).
_REFERENCE_DEFINITION = re.compile(
    r"^ {0,3}\[([^\]]+)\]:[ \t]*(?:\n[ \t]*)?<?([^\s>]+)>?.*$", re.MULTILINE
)


_MAX_PARENTHESES = 32


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _closing_brackets(text: str) -> dict[int, int]:
    """Map the index of each matched '[' to the index of its closing ']'.

    One pass with a stack, so an unmatched '[' costs nothing later (#1439).
    """
    matches: dict[int, int] = {}
    stack: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            stack.append(index)
        elif char == "]" and stack:
            matches[stack.pop()] = index
        index += 1
    return matches


def _destination(text: str, start: int) -> tuple[str, int, tuple[int, int] | None] | None:
    """Parse an inline destination and optional title at text[start] == '('.

    Return the URL, the index after the closing ')' and the title's span, or
    None. A bare destination may hold balanced parentheses up to
    _MAX_PARENTHESES deep, the cmark limit that CommonMark allows. The limit
    bounds the work of a run of unclosed destinations (#1439).
    """
    if start >= len(text) or text[start] != "(":
        return None
    index = start + 1
    while index < len(text) and text[index] in " \t\n":
        index += 1
    if index < len(text) and text[index] == "<":
        line_end = text.find("\n", index)
        close = text.find(">", index, len(text) if line_end < 0 else line_end)
        if close < 0:
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
                if depth > _MAX_PARENTHESES:
                    return None
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
            index += 1
        url = text[begin:index]
        if depth or not url:
            return None
    title = _TITLE.match(text, index)
    title_span = title.span() if title else None
    if title:
        index = title.end()
    while index < len(text) and text[index] in " \t\n":
        index += 1
    if index < len(text) and text[index] == ")":
        return url, index + 1, title_span
    return None


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _strip_code_blocks(text: str) -> str:
    """Blank fenced and indented code blocks, keeping one newline per line.

    A fence may be indented up to three columns past the content of the
    enclosing list item, and an unclosed fence runs to the end (CommonMark). An
    indented code block needs four columns past that content and cannot
    interrupt a paragraph. Block quotes are not modelled.
    """
    out: list[str] = []
    fence: tuple[str, int] | None = None
    content_offset = 0  # content column of the enclosing list item, if any
    previous = "start"  # the last non-blank line: "start", "code", "block" or "text"
    blank_before = True
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n").expandtabs(4)
        if fence is not None:
            close = _FENCE_CLOSE.match(line)
            if (
                close
                and close["fence"][0] == fence[0]
                and len(close["fence"]) >= fence[1]
                and len(close["indent"]) <= content_offset + 3
            ):
                fence = None
                previous, blank_before = "block", False
            out.append("\n")
            continue
        if not line.strip():
            out.append(raw_line)
            blank_before = True
            continue
        indent = _indent(line)
        item = _LIST_ITEM.match(line)
        if blank_before and indent < content_offset and not item:
            content_offset = 0
        opening = _FENCE_OPEN.match(line)
        if opening and len(opening["indent"]) <= content_offset + 3:
            fence = (opening["fence"][0], len(opening["fence"]))
            out.append("\n")
            continue
        # An indented code block cannot interrupt a paragraph.
        if indent >= content_offset + 4 and (blank_before or previous != "text"):
            out.append("\n")
            previous, blank_before = "code", False
            continue
        if item:
            content_offset = len(item["marker"]) + len(item["gap"] or " ")
        previous = "block" if _ATX_HEADING.match(line) else "text"
        blank_before = False
        out.append(raw_line)
    return "".join(out)


def _strip_code_spans(text: str) -> str:
    """Remove code spans: a backtick run closed by the next run of equal length.

    A span cannot cross a blank line here. An unmatched run is literal text. A
    backslash before a run escapes only its first backtick, so the rest of the
    run can still open a span. Inside a span a backslash is literal, so a
    closing run is never shortened.
    """
    runs = [(match.start(), match.end()) for match in _BACKTICKS.finditer(text)]
    by_length: dict[int, list[int]] = {}
    for position, (start, end) in enumerate(runs):
        by_length.setdefault(end - start, []).append(position)
    out: list[str] = []
    copied = 0
    position = 0
    while position < len(runs):
        start, end = runs[position]
        if start > 0 and text[start - 1] == "\\":
            start += 1
        candidates = by_length.get(end - start, [])
        following = bisect.bisect_right(candidates, position)
        closer = candidates[following] if start < end and following < len(candidates) else None
        if closer is None or _PARAGRAPH_BREAK.search(text, end, runs[closer][0]):
            position += 1
            continue
        out.append(text[copied:start])
        copied = runs[closer][1]
        position = closer + 1
    out.append(text[copied:])
    return "".join(out)


def _strip_link_titles(text: str) -> str:
    """Remove inline and reference-definition link titles, which hold no HTML."""
    text = _DEFINITION_TITLE.sub(r"\1", text)
    out: list[str] = []
    copied = 0
    index = 0
    while (start := text.find("](", index)) >= 0:
        destination = _destination(text, start + 1)
        if destination is None:
            index = start + 2
            continue
        _url, end, title = destination
        if title is not None and title[0] >= copied:
            out.append(text[copied : title[0]])
            copied = title[1]
        index = end
    out.append(text[copied:])
    return "".join(out)


def _raw_html(text: str) -> list[str]:
    """Return each CommonMark raw HTML construct in text, in order.

    The scan is linear: a closer that is missing after one opener is missing
    after every later opener too.
    """
    found: list[str] = []
    missing: set[str] = set()
    index = 0
    while (start := text.find("<", index)) >= 0:
        end: int | None = None
        if start > 0 and text[start - 1] == "\\":
            index = start + 1
            continue
        opener, closer = next(
            ((opener, closer) for opener, closer in _HTML_SPANS if text.startswith(opener, start)),
            ("<!", ">") if _DECLARATION.match(text, start) else ("", ""),
        )
        if closer:
            if closer not in missing:
                close = text.find(closer, start + len(opener))
                if close < 0:
                    missing.add(closer)
                else:
                    end = close + len(closer)
        elif tag := _HTML_TAG.match(text, start):
            end = tag.end()
        if end is None:
            index = start + 1
            continue
        found.append(text[start:end])
        index = end
    return found


def _inline_targets(
    text: str, definitions: dict[str, str], uses: dict[str, set[bool]]
) -> list[tuple[bool, str]]:
    """Return (is_image, url) for inline links and images, including the image
    inside a linked image. Record which reference definitions are used, and how."""
    targets: list[tuple[bool, str]] = []
    closing = _closing_brackets(text)
    index = 0
    while (start := text.find("[", index)) >= 0:
        if start > 0 and text[start - 1] == "\\":
            index = start + 1
            continue
        end = closing.get(start, -1)
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
            url, index, _title = destination
            targets.append((is_image, url))
        elif label in definitions:
            uses.setdefault(label, set()).add(is_image)
            index = reference.end() if reference else end + 1
        else:
            index = start + 1
            continue
        targets += _inline_targets(inner, definitions, uses)
    return targets


_GITHUB_HOSTS = {"github.com", "www.github.com"}
_RAW_HOSTS = {"raw.githubusercontent.com"}
# Each spelling of the main branch that GitHub serves (checked 2026-11-08).
_MAIN_REFS = (["main"], ["HEAD"], ["refs", "heads", "main"])


class RepositoryUrlError(ValueError):
    """A URL into this repository that GitHub cannot serve."""


def _after_main_ref(rest: list[str]) -> list[str] | None:
    for ref in _MAIN_REFS:
        if rest[: len(ref)] == ref:
            return rest[len(ref) :]
    return None


def _repository_path(url: str) -> tuple[list[str], bool] | None:
    """Map a URL to a path on this repository's main branch.

    Return the path segments and whether they must name a directory, or None
    when the URL does not point into the repository's main branch. The forms
    are `github.com` or `www.github.com` `blob`, `tree` or `raw` URLs and
    `raw.githubusercontent.com` URLs, on `main`, `HEAD` or `refs/heads/main`.
    `.` and `..` segments are resolved as a browser does. Raise
    RepositoryUrlError for a `VMx.git/...` path, which GitHub answers with 404,
    and for a path that climbs above the repository root.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host not in _GITHUB_HOSTS | _RAW_HOSTS:
        return None
    segments = [unquote(segment) for segment in parts.path.split("/")[1:]]
    if len(segments) < 2 or segments[0].casefold() != "thekaveh":
        return None
    repository = segments[1].casefold()
    if repository == "vmx.git" and any(segments[2:]):
        raise RepositoryUrlError("uses a VMx.git path, which GitHub does not serve")
    if repository != "vmx":
        return None
    rest = segments[2:]
    if host in _GITHUB_HOSTS and rest[:1] in (["blob"], ["tree"], ["raw"]):
        path, directory = _after_main_ref(rest[1:]), rest[0] == "tree"
    elif host in _RAW_HOSTS:
        path, directory = _after_main_ref(rest), False
    else:
        return None
    if path is None:
        return None
    resolved: list[str] = []
    for segment in path:
        if segment in ("", "."):
            continue
        if segment == "..":
            if not resolved:
                raise RepositoryUrlError("names a path above the repository root")
            resolved.pop()
            continue
        resolved.append(segment)
    return resolved, directory


def _tracked_tree(repo_root: Path) -> tuple[set[str], set[str]] | None:
    """Return the tracked files and directories when repo_root is a Git work tree root.

    Return None when it is not, or when Git is unavailable; the path check then
    reads only the file system.
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo_root.resolve():
            return None
        listed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0:
        return None
    files = {name for name in listed.stdout.decode("utf-8", "surrogateescape").split("\0") if name}
    directories = {
        "/".join(name.split("/")[:depth])
        for name in files
        for depth in range(1, name.count("/") + 1)
    }
    return files, directories


def _repository_path_exists(
    repo_root: Path,
    segments: list[str],
    *,
    directory: bool,
    tracked: tuple[set[str], set[str]] | None = None,
) -> bool:
    """Return whether the segments name an entry with exactly that spelling.

    GitHub paths are case-sensitive, so each segment must match a directory
    entry exactly, even on a case-insensitive file system. When tracked holds
    the Git index of repo_root, the entry must also be tracked, so an untracked
    or ignored file does not pass.
    """
    if tracked is not None and segments:
        files, directories = tracked
        if "/".join(segments) not in (directories if directory else files):
            return False
    current = repo_root
    for segment in segments:
        try:
            names = {entry.name for entry in os.scandir(current)}
        except OSError:
            return False
        if segment not in names:
            return False
        current = current / segment
    return current.is_dir() if directory else current.is_file()


def validate_readme(text: str, package_id: str, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Return errors for a packaged README that would not render outside the repository.

    A URL into this repository's main branch must name a path that exists in
    repo_root, the checked-out tree. When repo_root is a Git work tree, the
    path must also be tracked. A published README cannot change, so a dangling
    path there would stay broken on nuget.org.
    """
    errors: list[str] = []
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line != f"# {package_id}":
        errors.append(f"README must open with the heading '# {package_id}'")
    prose = _strip_code_spans(_strip_code_blocks(text))
    for match in _raw_html(_strip_link_titles(prose)):
        tag = " ".join(match.split())
        errors.append(f"README uses raw HTML, which nuget.org does not render: {tag}")
    definitions = {
        _label(label): url for label, url in reversed(_REFERENCE_DEFINITION.findall(prose))
    }
    uses: dict[str, set[bool]] = {}
    body = _REFERENCE_DEFINITION.sub("", prose)
    targets = _inline_targets(body, definitions, uses)
    targets += [(False, url) for url in _AUTOLINK.findall(body)]
    # A definition gets the rules of each way it is used; an unused one is a link.
    targets += [
        (is_image, url)
        for label, url in definitions.items()
        for is_image in sorted(uses.get(label, {False}))
    ]
    tracked: tuple[set[str], set[str]] | None = None
    tracked_loaded = False
    for is_image, url in dict.fromkeys(targets):
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
        try:
            repository_path = _repository_path(url)
        except RepositoryUrlError as error:
            errors.append(f"README {kind} {error}: {url}")
            continue
        if repository_path is None:
            continue
        if not tracked_loaded:
            tracked, tracked_loaded = _tracked_tree(repo_root), True
        if not _repository_path_exists(
            repo_root, repository_path[0], directory=repository_path[1], tracked=tracked
        ):
            errors.append(f"README {kind} names a path missing from the checked-out tree: {url}")
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
    dependencies_by_framework: dict[str, list[tuple[str, str]]],
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
            *dependencies_by_framework.get(framework, []),
        ]
        if sorted(dependencies) != sorted(expected_dependencies):
            errors.append(
                f"{framework} dependencies must be exactly "
                f"{sorted(expected_dependencies)}; found {sorted(dependencies)}"
            )
    return errors


def validate_package_pair(
    package_dir: Path,
    package_id: str,
    version: str,
    vmx_floor: str | None,
    *,
    repo_root: Path = REPO_ROOT,
    central_versions: dict[str, str] | None = None,
) -> list[str]:
    """Return contract errors for one main/symbol package pair.

    Dependency versions come from central_versions, by default the pins in
    langs/csharp/Directory.Packages.props.
    """
    errors: list[str] = []
    dependencies_by_framework = package_dependencies(package_id, central_versions)
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
                        for error in validate_readme(readme, package_id, repo_root=repo_root):
                            errors.append(f"{archive.name}: {error}")
                nuspec = f"{package_id}.nuspec"
                if nuspec in paths:
                    for error in _validate_nuspec(
                        package.read(nuspec),
                        package_id,
                        version,
                        vmx_floor,
                        symbols=symbols,
                        dependencies_by_framework=dependencies_by_framework,
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT / "langs" / "csharp" / "src")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="checked-out tree that README URLs into the main branch must resolve against",
    )
    parser.add_argument(
        "--central-packages",
        type=Path,
        default=CENTRAL_PACKAGES,
        help="Directory.Packages.props that sets the expected dependency versions",
    )
    args = parser.parse_args(argv)
    central_versions = central_package_versions(args.central_packages)
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
        for error in validate_package_pair(
            args.package_dir,
            package_id,
            version,
            vmx_floor,
            repo_root=args.repo_root,
            central_versions=central_versions,
        )
    ]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: validated {len(expected)} NuGet package and symbol pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
