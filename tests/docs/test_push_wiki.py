from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.docs.push_wiki import _env_with_identity, push_wiki


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def test_deploy_key_takes_precedence_over_token_askpass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = tmp_path / "wiki-key"
    key.touch()
    monkeypatch.setenv("WIKI_DEPLOY_KEY", str(key))
    monkeypatch.setenv("WIKI_TOKEN", "secret")

    env = _env_with_identity()

    assert env["GIT_SSH_COMMAND"].startswith(f"ssh -i {key}")
    assert "GIT_ASKPASS" not in env


def test_check_compares_live_wiki_without_committing_or_pushing(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "master")
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.com")
    (seed / "Home.md").write_text("# Current\n", encoding="utf-8")
    _git(seed, "add", "Home.md")
    _git(seed, "commit", "-m", "seed")

    remote = tmp_path / "wiki.git"
    _git(tmp_path, "clone", "--bare", str(seed), str(remote))
    original_head = _git(remote, "rev-parse", "master")

    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "Home.md").write_text("# Current\n", encoding="utf-8")
    assert push_wiki(generated, str(remote), push=False, check_published=True)

    (generated / "Home.md").write_text("# Updated\n", encoding="utf-8")
    assert not push_wiki(generated, str(remote), push=False, check_published=True)
    assert _git(remote, "rev-parse", "master") == original_head
    assert _git(remote, "show", "master:Home.md") == "# Current"
