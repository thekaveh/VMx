"""Unit tests for tools/check-rust-fixture-sync.py."""

from pathlib import Path

import check_rust_fixture_sync as crfs

FIXTURE_NAMES = (
    "command-truthtable.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)


def _fixture_tree(root: Path, copy_text: str = "{}\n") -> None:
    source = root / "spec" / "fixtures"
    package = root / "langs" / "rust" / "src" / "fixtures"
    source.mkdir(parents=True)
    package.mkdir(parents=True)
    for name in FIXTURE_NAMES:
        (source / name).write_text("{}\n", encoding="utf-8")
        (package / name).write_text(copy_text, encoding="utf-8")


def test_main_returns_zero_when_runtime_fixture_matches(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    monkeypatch.setattr(crfs, "repo_root", lambda: tmp_path)

    assert crfs.main() == 0
    assert "matches" in capsys.readouterr().out


def test_main_returns_one_when_runtime_fixture_drifts(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path, copy_text='{"drift": true}\n')
    monkeypatch.setattr(crfs, "repo_root", lambda: tmp_path)

    assert crfs.main() == 1
    assert "drifted" in capsys.readouterr().err


def test_main_returns_one_when_runtime_fixture_is_missing(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / "langs/rust/src/fixtures/lifecycle-transitions.json").unlink()
    monkeypatch.setattr(crfs, "repo_root", lambda: tmp_path)

    assert crfs.main() == 1
    assert "missing Rust fixture copy" in capsys.readouterr().err


def test_all_packaged_test_fixtures_are_checked() -> None:
    assert {Path(copy).name for _source, copy in crfs._FIXTURE_PAIRS} == set(FIXTURE_NAMES)
