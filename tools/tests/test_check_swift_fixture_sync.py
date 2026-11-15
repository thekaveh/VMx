"""Unit tests for tools/check-swift-fixture-sync.py."""

from pathlib import Path

import check_swift_fixture_sync as csfs

FIXTURE_NAMES = (
    "command-truthtable.json",
    "derived-properties.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)
COPY_DIR = Path("langs/swift/Sources/VMx/Resources")


def _fixture_tree(root: Path, copy_text: str = "{}\n") -> None:
    source = root / "spec" / "fixtures"
    resources = root / COPY_DIR
    source.mkdir(parents=True)
    resources.mkdir(parents=True)
    for name in FIXTURE_NAMES:
        (source / name).write_text("{}\n", encoding="utf-8")
        (resources / name).write_text(copy_text, encoding="utf-8")


def _use(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(csfs, "repo_root", lambda: root)


def test_main_returns_zero_when_copies_match(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)

    assert csfs.main() == 0
    assert "matches" in capsys.readouterr().out


def test_main_returns_one_when_copy_drifts(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path, copy_text='{"drift": true}\n')
    _use(monkeypatch, tmp_path)

    assert csfs.main() == 1
    assert "drifted" in capsys.readouterr().err


def test_main_returns_one_when_copy_is_missing(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / COPY_DIR / "derived-properties.json").unlink()
    _use(monkeypatch, tmp_path)

    assert csfs.main() == 1
    assert "missing Swift fixture copy" in capsys.readouterr().err


def test_main_fails_when_spec_fixture_has_no_copy(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / "spec" / "fixtures" / "probe.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert csfs.main() == 1
    assert f"missing Swift fixture copy: {COPY_DIR / 'probe.json'}" in capsys.readouterr().err


def test_main_fails_on_copy_with_no_spec_source(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / COPY_DIR / "stale.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert csfs.main() == 1
    err = capsys.readouterr().err
    assert f"unexpected Swift fixture copy: {COPY_DIR / 'stale.json'}" in err


def test_repository_copies_match_spec_fixtures() -> None:
    assert csfs.main() == 0
