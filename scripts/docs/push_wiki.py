from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_REMOTE = "git@github.com:thekaveh/VMx.wiki.git"


def _env_with_identity() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "github-actions[bot]")
    env.setdefault("GIT_AUTHOR_EMAIL", "41898282+github-actions[bot]@users.noreply.github.com")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    key_path = env.get("WIKI_DEPLOY_KEY")
    if key_path and Path(key_path).exists():
        env["GIT_SSH_COMMAND"] = f"ssh -i {key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    return env


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def sync_wiki(src: Path, repo_dir: Path) -> None:
    for item in repo_dir.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in src.iterdir():
        target = repo_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def push_wiki(src: Path, remote: str, *, push: bool) -> None:
    env = _env_with_identity()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "wiki"
        if push:
            _run(["git", "clone", "--depth", "1", remote, str(work)], Path(tmp), env)
        else:
            work.mkdir()
            _run(["git", "init", "-b", "master"], work, env)
        sync_wiki(src, work)
        _run(["git", "add", "-A"], work, env)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=work, env=env)
        if diff.returncode == 0:
            print("wiki already up to date")
            return
        _run(["git", "commit", "-m", "docs: sync generated wiki"], work, env)
        if push:
            _run(["git", "push", "origin", "HEAD:master"], work, env)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="generated/wiki")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    remote = os.environ.get("WIKI_REMOTE", DEFAULT_REMOTE)
    push_wiki(Path(args.src), remote, push=args.push and not args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
