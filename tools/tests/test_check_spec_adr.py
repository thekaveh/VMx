"""Tests for tools/check-spec-adr.py, the ADR rule of the spec-discipline check.

Each scenario builds a scratch repository in which the base branch moves after
the pull request branches. The script receives the moved base tip as its base
SHA, as the workflow does, so only a diff from the merge base sees just the
pull request's own changes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check-spec-adr.py"
# The well-known empty tree of a SHA-1 repository, used for an unrelated base commit.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=VMx Test",
            "-c",
            "user.email=vmx-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


def _commit(repo: Path, changes: dict[str, str | None], message: str) -> str:
    """Write or delete (None) each path, commit everything, and return the new HEAD."""
    for path, content in changes.items():
        target = repo / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one ADR and spec text; develop is the base branch."""
    path = tmp_path / "scratch"
    path.mkdir()
    _git(path, "init", "-q", "-b", "develop")
    _commit(
        path,
        {
            "spec/04-commands.md": "commands v1\n",
            "spec/ADRs/0001-first.md": "adr one\n",
            "src/app.txt": "app v1\n",
        },
        "init",
    )
    return path


def _pull_request(repo: Path, changes: dict[str, str | None]) -> str:
    """Branch `feature` from the develop tip, commit `changes`, and return its head.

    Leaves `develop` checked out, so the caller can move the base afterwards.
    """
    _git(repo, "checkout", "-q", "-b", "feature")
    head = _commit(repo, changes, "pull request")
    _git(repo, "checkout", "-q", "develop")
    return head


def _run(
    repo: Path, base_sha: str, head_sha: str, labels: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["PR_LABELS_JSON"] = json.dumps(labels or [])
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base-sha", base_sha, "--head-sha", head_sha],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_base_spec_change_made_after_branching_is_not_counted(repo: Path) -> None:
    head = _pull_request(repo, {"src/app.txt": "app v2\n"})
    base_tip = _commit(
        repo,
        {"spec/04-commands.md": "commands v2\n", "spec/ADRs/0002-second.md": "adr two\n"},
        "develop moves",
    )

    result = _run(repo, base_tip, head)

    assert result.returncode == 0, result.stdout
    assert "no spec text changed" in result.stdout


def test_adr_deleted_on_moved_base_is_still_required(repo: Path) -> None:
    head = _pull_request(repo, {"spec/04-commands.md": "commands v2\n"})
    base_tip = _commit(repo, {"spec/ADRs/0001-first.md": None}, "develop drops an ADR")

    result = _run(repo, base_tip, head)

    assert result.returncode == 1, result.stdout
    assert "no new ADR was added" in result.stdout


def test_spec_change_with_a_new_adr_passes(repo: Path) -> None:
    head = _pull_request(
        repo,
        {
            "spec/04-commands.md": "commands v2\n",
            "spec/ADRs/0003-v2.0-dotted-title.md": "adr three\n",
        },
    )

    result = _run(repo, _git(repo, "rev-parse", "develop"), head)

    assert result.returncode == 0, result.stdout
    assert "spec/ADRs/0003-v2.0-dotted-title.md" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        "spec/ADRs/notes.txt",
        "spec/ADRs/draft-0003-title.md",
        "spec/ADRs/0003.md",
        "spec/ADRs/nested/0003-title.md",
    ],
)
def test_added_file_under_adrs_that_is_not_a_numbered_adr_does_not_satisfy_the_rule(
    repo: Path, path: str
) -> None:
    head = _pull_request(repo, {"spec/04-commands.md": "commands v2\n", path: "note\n"})

    result = _run(repo, _git(repo, "rev-parse", "develop"), head)

    assert result.returncode == 1, result.stdout
    assert "no new ADR was added" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        "spec/README.md",
        "spec/HISTORY.md",
        "spec/VERSION",
        "spec/12-conformance.md",
        "spec/fixtures/lifecycle-transitions.json",
        "spec/proposals/2026-01-01-idea.md",
    ],
)
def test_exempt_spec_files_do_not_need_an_adr(repo: Path, path: str) -> None:
    head = _pull_request(repo, {path: "changed\n"})

    result = _run(repo, _git(repo, "rev-parse", "develop"), head)

    assert result.returncode == 0, result.stdout


def test_no_adr_needed_label_bypasses_the_rule(repo: Path) -> None:
    head = _pull_request(repo, {"spec/04-commands.md": "commands typo fixed\n"})

    result = _run(repo, _git(repo, "rev-parse", "develop"), head, labels=["no-adr-needed"])

    assert result.returncode == 0, result.stdout
    assert "bypassed by 'no-adr-needed' label" in result.stdout


@pytest.mark.parametrize("labels", [[], ["no-adr-needed-soon"], ["adr-no-adr-needed"]])
def test_only_the_exact_label_bypasses_the_rule(repo: Path, labels: list[str]) -> None:
    head = _pull_request(repo, {"spec/04-commands.md": "commands v2\n"})

    result = _run(repo, _git(repo, "rev-parse", "develop"), head, labels=labels)

    assert result.returncode == 1, result.stdout
    assert "no new ADR was added" in result.stdout


def test_base_with_no_common_ancestor_fails_the_rule(repo: Path) -> None:
    head = _pull_request(repo, {"spec/04-commands.md": "commands v2\n"})
    unrelated = _git(repo, "commit-tree", EMPTY_TREE, "-m", "unrelated base")

    result = _run(repo, unrelated, head)

    assert result.returncode == 1, result.stdout
    assert "No merge base" in result.stdout
