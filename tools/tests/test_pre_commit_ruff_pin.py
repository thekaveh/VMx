"""Keep the pre-commit ruff hook on the ruff version that CI runs (#1335).

CI runs ruff from the locked `langs/python` environment. No Dependabot entry
covers `.pre-commit-config.yaml`, so this test fails when a lock update moves
ruff and the hook `rev` stays behind.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
PYTHON_LOCK = ROOT / "langs/python/uv.lock"

# uv.lock is TOML, but tomllib needs Python 3.11 and the tools tests also run
# on the 3.10 floor. Each `[[package]]` table starts with `name` then `version`.
_LOCKED_PACKAGE = re.compile(
    r'^name = "(?P<name>[^"]+)"\nversion = "(?P<version>[^"]+)"', re.MULTILINE
)
_RUFF_REPO = re.compile(
    r"^\s*-\s*repo:\s*https://github\.com/astral-sh/ruff-pre-commit\s*\n\s*rev:\s*v?(?P<rev>\S+)",
    re.MULTILINE,
)


def hook_ruff_version(config_text: str) -> str:
    match = _RUFF_REPO.search(config_text)
    if match is None:
        raise AssertionError("the pre-commit config has no astral-sh/ruff-pre-commit rev")
    return match.group("rev").strip("'\"")


def locked_ruff_version(lock_text: str) -> str:
    versions = {
        match.group("version")
        for match in _LOCKED_PACKAGE.finditer(lock_text)
        if match.group("name") == "ruff"
    }
    if len(versions) != 1:
        raise AssertionError(f"expected one locked ruff version, found {sorted(versions)}")
    return versions.pop()


def ruff_pin_mismatch(config_text: str, lock_text: str) -> str | None:
    hook = hook_ruff_version(config_text)
    locked = locked_ruff_version(lock_text)
    if hook == locked:
        return None
    return (
        f".pre-commit-config.yaml pins ruff-pre-commit v{hook}, but langs/python/uv.lock "
        f"resolves ruff {locked}; set the hook rev to v{locked}"
    )


def _config(rev: str) -> str:
    return (
        "repos:\n"
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        f"    rev: {rev}\n"
        "    hooks:\n"
        "      - id: ruff-check\n"
    )


def _lock(version: str) -> str:
    return f'version = 1\n\n[[package]]\nname = "ruff"\nversion = "{version}"\n'


def test_hook_rev_matches_the_locked_ruff_version() -> None:
    mismatch = ruff_pin_mismatch(
        PRE_COMMIT.read_text(encoding="utf-8"), PYTHON_LOCK.read_text(encoding="utf-8")
    )
    assert mismatch is None, mismatch


def test_equal_versions_pass() -> None:
    assert ruff_pin_mismatch(_config("v0.17.3"), _lock("0.17.3")) is None


@pytest.mark.parametrize(("rev", "locked"), [("v0.16.0", "0.17.3"), ("v0.17.3", "0.17.4")])
def test_different_versions_fail(rev: str, locked: str) -> None:
    mismatch = ruff_pin_mismatch(_config(rev), _lock(locked))
    assert mismatch is not None
    assert f"set the hook rev to v{locked}" in mismatch


def test_missing_hook_is_reported() -> None:
    with pytest.raises(AssertionError, match="ruff-pre-commit"):
        hook_ruff_version("repos: []\n")
