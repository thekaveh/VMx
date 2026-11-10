"""A new ADR changes no committed diagram on the host that runs this test (#1477).

The test copies the tracked repository files into a fresh Git repository, adds
an empty ``spec/ADRs/9999-test.md``, runs both diagram generators in write
mode, and expects ``git status --porcelain`` to list only that ADR and,
optionally, the architecture triplets that may carry an ADR count. The docs
workflow runs it on ``ubuntu-24.04`` through ``make docs-check``, so CI proves
that the committed PNGs (rendered on macOS) survive a generator run there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NEW_ADR = "spec/ADRs/9999-test.md"
# The issue allows these triplets to change, because an ADR count may appear
# in the architecture diagrams. Every other path must stay unchanged.
ALLOWED_PREFIXES = ("assets/architecture.", "docs/assets/diagrams/system-architecture.")
GENERATORS = ("tools/generate-doc-diagrams.py", "docs/assets/diagrams/generate_diagrams.py")


def _git(cwd: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=docs-test",
            "-c",
            "user.email=docs-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    return completed.stdout


def _copy_tracked_tree(destination: Path) -> None:
    listing = _git(ROOT, "ls-files", "-z")
    for name in filter(None, listing.split("\0")):
        source = ROOT / name
        if not source.exists() and not source.is_symlink():
            continue  # deleted in the working tree
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


def test_new_adr_changes_no_unrelated_diagram(tmp_path: Path) -> None:
    missing = [tool for tool in ("rsvg-convert", "pngquant") if shutil.which(tool) is None]
    if missing:
        message = f"diagram rasterizers not on PATH: {', '.join(missing)}"
        if os.environ.get("CI"):
            pytest.fail(message)  # the docs workflow installs both tools
        pytest.skip(message)

    clone = tmp_path / "repo"
    _copy_tracked_tree(clone)
    _git(clone, "init", "--quiet")
    _git(clone, "add", "--all")
    _git(clone, "commit", "--quiet", "--no-verify", "-m", "snapshot")

    (clone / NEW_ADR).write_text("", encoding="utf-8")
    for generator in GENERATORS:
        completed = subprocess.run(
            [sys.executable, generator],
            cwd=clone,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert completed.returncode == 0, (
            f"{generator} failed:\n{completed.stdout}{completed.stderr}"
        )

    status = _git(clone, "status", "--porcelain", "--untracked-files=all").splitlines()
    paths = [line[3:] for line in status]
    assert f"?? {NEW_ADR}" in status
    unexpected = [
        path for path in paths if path != NEW_ADR and not path.startswith(ALLOWED_PREFIXES)
    ]
    assert unexpected == [], f"a new ADR changed unrelated files: {unexpected}"
