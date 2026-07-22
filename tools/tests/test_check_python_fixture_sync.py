"""Unit tests for tools/check-python-fixture-sync.py."""

from pathlib import Path

import check_python_fixture_sync as cpfs

FIXTURE_NAMES = (
    "command-truthtable.json",
    "derived-properties.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)


def _fixture_tree(root: Path, copy_text: str = "{}\n") -> None:
    source = root / "spec" / "fixtures"
    runtime_package = root / "langs" / "python" / "src" / "vmx" / "lifecycle" / "_data"
    test_package = root / "langs" / "python" / "tests" / "conformance" / "fixtures" / "data"
    source.mkdir(parents=True)
    runtime_package.mkdir(parents=True)
    test_package.mkdir(parents=True)
    for name in FIXTURE_NAMES:
        (source / name).write_text("{}\n", encoding="utf-8")
        (test_package / name).write_text(copy_text, encoding="utf-8")
    (runtime_package / "lifecycle-transitions.json").write_text(copy_text, encoding="utf-8")


def test_main_returns_zero_when_runtime_fixture_matches(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    monkeypatch.setattr(cpfs, "repo_root", lambda: tmp_path)

    assert cpfs.main() == 0
    assert "matches" in capsys.readouterr().out


def test_main_returns_one_when_runtime_fixture_drifts(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path, copy_text='{"drift": true}\n')
    monkeypatch.setattr(cpfs, "repo_root", lambda: tmp_path)

    assert cpfs.main() == 1
    assert "drifted" in capsys.readouterr().err


def test_main_returns_one_when_runtime_fixture_is_missing(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / "langs/python/src/vmx/lifecycle/_data/lifecycle-transitions.json").unlink()
    monkeypatch.setattr(cpfs, "repo_root", lambda: tmp_path)

    assert cpfs.main() == 1
    assert "missing Python fixture copy" in capsys.readouterr().err


def test_all_sdist_test_fixtures_are_checked() -> None:
    test_copy_names = {
        Path(copy).name
        for _source, copy in cpfs._FIXTURE_PAIRS
        if "/tests/conformance/fixtures/data/" in copy
    }
    assert test_copy_names == set(FIXTURE_NAMES)
