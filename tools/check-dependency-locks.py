#!/usr/bin/env python3
"""Check that the uv and docs locks equal the output of their regeneration commands.

Dependabot can write a `uv.lock` with a newer uv than CI, which changes the lock
revision and rewrites markers, and it can regenerate `docs/requirements.txt`
without the pins that the file's header command writes (#1361). This check runs
with the uv that CI pins. It regenerates each lock in place, compares the bytes
with the committed file, and restores the committed file. A failure names the
command that regenerates the lock. The maintenance document
`docs/maintenance/2026-11-09-dependency-lock-regeneration.md` lists the
regeneration command of every ecosystem.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_REQUIREMENTS = Path("docs/requirements.txt")
_REVISION = re.compile(r"^revision = (\d+)$", re.MULTILINE)
_HEADER_COMMAND = re.compile(r"^#\s+(uv pip compile .+)$", re.MULTILINE)
_TIMEOUT = 600


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False, timeout=_TIMEOUT
    )


def uv_version(uv: str) -> str:
    result = _run([uv, "--version"], cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"{uv} --version failed: {result.stderr.strip()}")
    return result.stdout.split()[1]


def lock_revision(text: str) -> int | None:
    match = _REVISION.search(text)
    return int(match.group(1)) if match else None


def written_revision(uv: str) -> int:
    """Return the lock revision that this uv writes for a new lock."""
    with tempfile.TemporaryDirectory(prefix="vmx-uv-probe-") as directory:
        project = Path(directory)
        (project / "pyproject.toml").write_text(
            '[project]\nname = "probe"\nversion = "0"\nrequires-python = ">=3.10"\n'
            "dependencies = []\n",
            encoding="utf-8",
        )
        result = _run([uv, "lock", "--offline", "--project", str(project)], cwd=project)
        if result.returncode != 0:
            raise RuntimeError(f"uv lock on an empty probe project failed: {result.stderr}")
        revision = lock_revision((project / "uv.lock").read_text(encoding="utf-8"))
    if revision is None:
        raise RuntimeError("the probe lock has no revision line")
    return revision


def uv_projects(repo_root: Path) -> list[Path]:
    """Return each directory that holds a tracked uv.lock, relative to repo_root."""
    listed = _run(["git", "ls-files", "-z", "--", "*uv.lock", "uv.lock"], cwd=repo_root)
    if listed.returncode == 0 and listed.stdout:
        locks = [Path(name) for name in listed.stdout.split("\0") if name]
    else:
        locks = [
            path.relative_to(repo_root)
            for path in repo_root.rglob("uv.lock")
            if not {".venv", "node_modules"} & set(path.parts)
        ]
    return sorted(lock.parent for lock in locks)


def _regenerate(path: Path, args: list[str], cwd: Path) -> tuple[bool, str]:
    """Run args, report whether path changed, and restore the committed bytes."""
    committed = path.read_bytes()
    try:
        result = _run(args, cwd=cwd)
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()
        return path.read_bytes() != committed, ""
    finally:
        path.write_bytes(committed)


def check_uv_locks(
    repo_root: Path, projects: Iterable[Path], *, uv: str, version: str, revision: int
) -> list[str]:
    issues: list[str] = []
    for project in projects:
        lock = repo_root / project / "uv.lock"
        command = f"uv lock --project {project.as_posix()}"
        found = lock_revision(lock.read_text(encoding="utf-8"))
        if found != revision:
            issues.append(
                f"{lock.relative_to(repo_root)}: lock revision {found}, but uv {version} writes "
                f"revision {revision}. A newer uv wrote this lock. Restore the lock from the "
                f"base branch and run, with uv {version}: {command} --upgrade-package "
                "<package>==<version>"
            )
            continue
        changed, error = _regenerate(lock, [uv, "lock", "--project", str(project)], repo_root)
        if error:
            issues.append(f"{lock.relative_to(repo_root)}: {command} failed: {error}")
        elif changed:
            issues.append(
                f"{lock.relative_to(repo_root)} differs from the output of: {command} "
                f"(uv {version}); run it and commit the result"
            )
    return issues


def docs_command(requirements: Path) -> list[str] | None:
    match = _HEADER_COMMAND.search(requirements.read_text(encoding="utf-8"))
    return shlex.split(match.group(1)) if match else None


def check_docs_requirements(repo_root: Path, *, uv: str, version: str) -> list[str]:
    requirements = repo_root / DOCS_REQUIREMENTS
    command = docs_command(requirements)
    if command is None or "--output-file" not in command:
        return [
            f"{DOCS_REQUIREMENTS}: the header names no `uv pip compile ... --output-file` command"
        ]
    output = command[command.index("--output-file") + 1]
    if Path(output) != DOCS_REQUIREMENTS:
        return [f"{DOCS_REQUIREMENTS}: the header command writes {output}, not this file"]
    shown = " ".join(command)
    changed, error = _regenerate(requirements, [uv, *command[1:]], repo_root)
    if error:
        return [f"{DOCS_REQUIREMENTS}: {shown} failed: {error}"]
    if changed:
        return [
            f"{DOCS_REQUIREMENTS} differs from the output of its header command: {shown} "
            f"(uv {version}); run it and commit the result"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uv", default="uv", help="uv executable; CI pins its version")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        version = uv_version(args.uv)
        revision = written_revision(args.uv)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    projects = uv_projects(repo_root)
    issues = check_uv_locks(repo_root, projects, uv=args.uv, version=version, revision=revision)
    issues += check_docs_requirements(repo_root, uv=args.uv, version=version)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(projects)} uv locks and {DOCS_REQUIREMENTS} equal the output of their "
        f"regeneration commands with uv {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
