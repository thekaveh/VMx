"""Unit tests for tools/check-typescript-schema-sync.py."""

import subprocess
from pathlib import Path

import check_typescript_schema_sync as ctss


def _mock_tracked(monkeypatch, *names: str) -> None:
    monkeypatch.setattr(ctss, "_tracked_json_names", lambda _root, _directory: set(names))


def _sync_tree(root: Path) -> None:
    pairs = (("spec/schemas", "langs/typescript/src/conformance/schemas", "schema.json"),)
    for source_rel, copy_rel, name in pairs:
        source = root / source_rel
        copy = root / copy_rel
        source.mkdir(parents=True)
        copy.mkdir(parents=True)
        (source / name).write_text("{}\n", encoding="utf-8")
        (copy / name).write_text("{}\n", encoding="utf-8")


def test_main_reports_repository_lookup_timeout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        ctss,
        "repo_root",
        lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 1)),
    )

    assert ctss.main() == 2
    assert "unable to locate repository root" in capsys.readouterr().err


def test_main_accepts_exact_fixture_and_schema_inventories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _sync_tree(tmp_path)
    monkeypatch.setattr(ctss, "repo_root", lambda: tmp_path)
    _mock_tracked(monkeypatch, "schema.json")

    assert ctss.main() == 0


def test_main_rejects_drifted_schema(tmp_path: Path, monkeypatch, capsys) -> None:
    _sync_tree(tmp_path)
    schema = tmp_path / "langs/typescript/src/conformance/schemas/schema.json"
    schema.write_text('{"drift": true}\n', encoding="utf-8")
    monkeypatch.setattr(ctss, "repo_root", lambda: tmp_path)
    _mock_tracked(monkeypatch, "schema.json")

    assert ctss.main() == 1
    assert "drifted" in capsys.readouterr().err


def test_main_rejects_missing_tracked_copy(tmp_path: Path, monkeypatch, capsys) -> None:
    _sync_tree(tmp_path)
    (tmp_path / "langs/typescript/src/conformance/schemas/schema.json").unlink()
    monkeypatch.setattr(ctss, "repo_root", lambda: tmp_path)
    _mock_tracked(monkeypatch, "schema.json")

    assert ctss.main() == 1
    assert "missing TypeScript tracked copy" in capsys.readouterr().err


def test_main_rejects_extra_tracked_copy(tmp_path: Path, monkeypatch, capsys) -> None:
    _sync_tree(tmp_path)
    extra = tmp_path / "langs/typescript/src/conformance/schemas/extra.json"
    extra.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ctss, "repo_root", lambda: tmp_path)
    _mock_tracked(monkeypatch, "schema.json", "extra.json")

    assert ctss.main() == 1
    assert "unexpected TypeScript tracked copy" in capsys.readouterr().err


def test_main_rejects_schema_recreated_as_untracked(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _sync_tree(tmp_path)
    monkeypatch.setattr(ctss, "repo_root", lambda: tmp_path)
    _mock_tracked(monkeypatch)

    assert ctss.main() == 1
    assert "schema copy is not tracked" in capsys.readouterr().err
