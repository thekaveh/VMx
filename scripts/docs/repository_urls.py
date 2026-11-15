"""Map GitHub URLs into this repository's main branch onto repository paths.

The NuGet README checker (`tools/check-nuget-package.py`) uses the same rules.
This module is a port, not an import: that checker has a hyphenated file name
and is loaded by file path in the tools tests. Keep the two in step.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


def repository_path(url: str) -> tuple[list[str], bool] | None:
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


def tracked_tree(repo_root: Path) -> tuple[set[str], set[str]] | None:
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


def repository_path_exists(
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
