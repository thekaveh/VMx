"""Unit tests for tools/check-layer-imports.py."""

import textwrap
from pathlib import Path

import check_layer_imports as cli


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_layer_of_finds_layer_by_path_part() -> None:
    layers = ["Models", "ViewModels", "Views"]
    assert cli._layer_of(("examples", "csharp", "Models", "Foo.cs"), layers) == "Models"
    assert cli._layer_of(("Views", "Adapter", "Bridge.cs"), layers) == "Views"
    assert cli._layer_of(("Program.cs",), layers) is None


def test_python_layer_from_import_picks_head() -> None:
    layers = ["models", "viewmodels", "views"]
    assert cli._python_layer_from_import("models.note", layers) == "models"
    assert cli._python_layer_from_import("views.adapter.property", layers) == "views"
    assert cli._python_layer_from_import("external.lib", layers) is None


def test_check_flavor_flags_viewmodel_importing_view(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["python"]
    repo_root = tmp_path
    base = repo_root / cfg["root"]
    _write(
        base / "models" / "note.py",
        """\
        class NoteModel: pass
        """,
    )
    _write(
        base / "viewmodels" / "note_vm.py",
        """\
        from notes_showcase.views.app import App  # forbidden: VM -> View
        """,
    )
    violations = cli.check_flavor("python", cfg, repo_root)
    assert any("forbidden import of views from viewmodels" in v for v in violations)


def test_main_exits_zero_with_empty_flavor_roots(tmp_path: Path, monkeypatch, capsys) -> None:
    """main() returns 0 when each flavor root exists but contains no source."""
    for cfg in cli.FLAVORS.values():
        (tmp_path / cfg["root"]).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sys.argv", ["check-layer-imports.py", "--root", str(tmp_path)])
    assert cli.main() == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_exits_one_on_violation(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg = cli.FLAVORS["python"]
    base = tmp_path / cfg["root"]
    _write(base / "models" / "note.py", "class N: pass\n")
    _write(
        base / "viewmodels" / "vm.py",
        "from notes_showcase.views.app import App\n",
    )
    monkeypatch.setattr("sys.argv", ["check-layer-imports.py", "--root", str(tmp_path)])
    assert cli.main() == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_check_flavor_accepts_adapter_exception_for_csharp(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["csharp"]
    base = tmp_path / cfg["root"]
    _write(
        base / "ViewModels" / "Vm.cs",
        """\
        using NotesShowcase.Views.Adapter;  // allowed adapter exception
        public class Vm { }
        """,
    )
    violations = cli.check_flavor("csharp", cfg, tmp_path)
    assert violations == []
