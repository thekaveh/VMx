"""Unit tests for tools/check-python-fixture-sync.py."""

import subprocess
from pathlib import Path

import check_python_fixture_sync as cpfs

FIXTURE_NAMES = (
    "command-truthtable.json",
    "derived-properties.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)
RUNTIME_DIR = Path("langs/python/src/vmx/lifecycle/_data")
TEST_DIR = Path("langs/python/tests/conformance/fixtures/data")


def test_main_reports_repository_lookup_timeout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cpfs,
        "repo_root",
        lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 1)),
    )

    assert cpfs.main() == 2
    assert "unable to locate repository root" in capsys.readouterr().err


def _fixture_tree(root: Path, copy_text: str = "{}\n") -> None:
    source = root / "spec" / "fixtures"
    source.mkdir(parents=True)
    (root / RUNTIME_DIR).mkdir(parents=True)
    (root / TEST_DIR).mkdir(parents=True)
    for name in FIXTURE_NAMES:
        (source / name).write_text("{}\n", encoding="utf-8")
        (root / TEST_DIR / name).write_text(copy_text, encoding="utf-8")
    (root / RUNTIME_DIR / "lifecycle-transitions.json").write_text(copy_text, encoding="utf-8")


def _use(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(cpfs, "repo_root", lambda: root)


def test_main_returns_zero_when_copies_match(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 0
    assert "matches" in capsys.readouterr().out


def test_main_returns_one_when_copy_drifts(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path, copy_text='{"drift": true}\n')
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    assert "drifted" in capsys.readouterr().err


def test_main_returns_one_when_runtime_copy_is_missing(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / RUNTIME_DIR / "lifecycle-transitions.json").unlink()
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    assert "missing Python fixture copy" in capsys.readouterr().err


def test_main_returns_one_when_test_copy_is_missing(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / TEST_DIR / "message-ordering.json").unlink()
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    assert "missing Python fixture copy" in capsys.readouterr().err


def test_main_fails_when_spec_fixture_has_no_copy(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / "spec" / "fixtures" / "probe.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    err = capsys.readouterr().err
    assert f"missing Python fixture copy: {TEST_DIR / 'probe.json'}" in err
    assert f"missing Python fixture copy: {RUNTIME_DIR / 'probe.json'}" in err


def test_main_fails_when_exempt_fixture_is_copied_to_runtime(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / RUNTIME_DIR / "command-truthtable.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    err = capsys.readouterr().err
    assert f"unexpected Python fixture copy: {RUNTIME_DIR / 'command-truthtable.json'}" in err


def test_main_fails_on_test_copy_with_no_spec_source(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / TEST_DIR / "stale.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cpfs.main() == 1
    err = capsys.readouterr().err
    assert f"unexpected Python fixture copy: {TEST_DIR / 'stale.json'}" in err


def test_main_fails_when_exemption_names_no_spec_fixture(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cpfs,
        "_COPY_DIRECTORIES",
        {str(RUNTIME_DIR): frozenset({"renamed-away.json"}), str(TEST_DIR): frozenset()},
    )

    assert cpfs.main() == 1
    assert "renamed-away.json" in capsys.readouterr().err


def test_repository_copies_match_spec_fixtures() -> None:
    assert cpfs.main() == 0
