#!/usr/bin/env python3
"""Validate exact VMx Python wheel and sdist contents before publication."""

from __future__ import annotations

import argparse
import email
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath


def _safe_unique(names: Iterable[str]) -> list[str]:
    result = list(names)
    if len(result) != len(set(result)):
        raise ValueError("archive contains duplicate entries")
    for name in result:
        path = PurePosixPath(name)
        if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in path.parts:
            raise ValueError(f"archive contains unsafe entry {name!r}")
    return result


def _exact(actual: set[str], expected: set[str], label: str) -> None:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ValueError(f"{label} inventory mismatch: missing={missing}, unexpected={unexpected}")


def _tracked_python_files(repo: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "langs/python"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {
        path.removeprefix("langs/python/")
        for path in result.stdout.splitlines()
        if path.startswith("langs/python/")
    }


def _metadata(raw: bytes, version: str, label: str) -> None:
    message = email.message_from_bytes(raw)
    if message.get("Name") != "vmx" or message.get("Version") != version:
        raise ValueError(f"{label} metadata must declare vmx {version}")


def check_wheel(path: Path, repo: Path, version: str) -> None:
    dist_info = f"vmx-{version}.dist-info"
    source_files = {
        tracked.removeprefix("src/")
        for tracked in _tracked_python_files(repo)
        if tracked.startswith("src/vmx/")
    }
    expected = source_files | {
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        f"{dist_info}/RECORD",
        f"{dist_info}/licenses/LICENSE",
        f"{dist_info}/licenses/NOTICE",
    }
    with zipfile.ZipFile(path) as archive:
        if any((info.external_attr >> 16) & 0o170000 == 0o120000 for info in archive.infolist()):
            raise ValueError("wheel must not contain symbolic links")
        names = _safe_unique(info.filename for info in archive.infolist() if not info.is_dir())
        _exact(set(names), expected, "wheel")
        _metadata(archive.read(f"{dist_info}/METADATA"), version, "wheel")
    for required in ("vmx/py.typed", "vmx/lifecycle/_data/lifecycle-transitions.json"):
        if required not in expected:
            raise ValueError(f"wheel is missing required runtime entry {required}")


def check_sdist(path: Path, repo: Path, version: str) -> None:
    root = f"vmx-{version}"
    expected = {f"{root}/{name}" for name in _tracked_python_files(repo)} | {
        f"{root}/.gitignore",
        f"{root}/PKG-INFO",
    }
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if any(member.issym() or member.islnk() for member in members):
            raise ValueError("sdist must not contain links")
        names = _safe_unique(member.name for member in members if member.isfile())
        _exact(set(names), expected, "sdist")
        metadata = archive.extractfile(f"{root}/PKG-INFO")
        if metadata is None:
            raise ValueError("sdist is missing PKG-INFO")
        _metadata(metadata.read(), version, "sdist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        wheels = sorted(args.dist.glob("vmx-*.whl"))
        sdists = sorted(args.dist.glob("vmx-*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError("dist must contain exactly one VMx wheel and one sdist")
        version = wheels[0].name.removeprefix("vmx-").split("-", 1)[0]
        if sdists[0].name != f"vmx-{version}.tar.gz":
            raise ValueError("wheel and sdist versions differ")
        check_wheel(wheels[0], args.repo_root, version)
        check_sdist(sdists[0], args.repo_root, version)
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        print(f"FAIL: Python package contract: {error}", file=sys.stderr)
        return 1
    print(f"OK: exact Python wheel and sdist contract for vmx {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
