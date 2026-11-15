"""Unit tests for tools/check-layer-imports.py."""

import textwrap
from pathlib import Path

import check_layer_imports as cli
import pytest


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


# --- Python: relative imports, package-name imports, syntax errors -----------


@pytest.mark.parametrize(
    "body",
    [
        "from ..views.note_widget import NoteWidget\n",
        "from notes_showcase import views\n",
        "from .. import views\n",
    ],
    ids=["relative-module", "package-name-import", "relative-package-name-import"],
)
def test_python_forms_flag_viewmodel_importing_view(tmp_path: Path, body: str) -> None:
    cfg = cli.FLAVORS["python"]
    _write(tmp_path / cfg["root"] / "models" / "note.py", "class N: pass\n")
    _write(tmp_path / cfg["root"] / "viewmodels" / "vm.py", body)
    violations = cli.check_flavor("python", cfg, tmp_path)
    assert len(violations) == 1
    assert "forbidden import of views from viewmodels" in violations[0]


def test_python_adapter_exception_passes_relative_and_absolute(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["python"]
    _write(
        tmp_path / cfg["root"] / "viewmodels" / "vm.py",
        """\
        from notes_showcase.views.adapter import bind_command
        from ..views.adapter.property import bind_derived_property
        """,
    )
    assert cli.check_flavor("python", cfg, tmp_path) == []


def test_python_syntax_error_is_a_violation_not_a_traceback(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["python"]
    _write(tmp_path / cfg["root"] / "models" / "note.py", "class NoteModel(:\n    pass\n")
    violations = cli.check_flavor("python", cfg, tmp_path)
    assert len(violations) == 1
    assert "syntax error" in violations[0]


# --- C#: alias, global, namespace-qualified and bare qualified references ----


@pytest.mark.parametrize(
    "body",
    [
        "using V = NotesShowcase.Views.MainWindow;\npublic class Vm { }\n",
        "global using NotesShowcase.Views;\npublic class Vm { }\n",
        "public class Vm { object W = new NotesShowcase.Views.MainWindow(); }\n",
        "public class Vm { object W = typeof(Views.MainWindow); }\n",
    ],
    ids=["alias-using", "global-using", "qualified-name", "bare-qualified-name"],
)
def test_csharp_forms_flag_viewmodel_referencing_view(tmp_path: Path, body: str) -> None:
    cfg = cli.FLAVORS["csharp"]
    _write(tmp_path / cfg["root"] / "ViewModels" / "Vm.cs", body)
    violations = cli.check_flavor("csharp", cfg, tmp_path)
    assert len(violations) == 1
    assert "forbidden import of Views from ViewModels" in violations[0]


def test_csharp_member_access_named_views_passes(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["csharp"]
    _write(
        tmp_path / cfg["root"] / "ViewModels" / "Vm.cs",
        """\
        public class Vm {
            public int Count => this.Views.Count;
            public int Other => provider.Views.Count;
        }
        """,
    )
    assert cli.check_flavor("csharp", cfg, tmp_path) == []


def test_csharp_comments_and_strings_do_not_count(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["csharp"]
    _write(
        tmp_path / cfg["root"] / "ViewModels" / "Vm.cs",
        """\
        // using NotesShowcase.Views.MainWindow;
        /* global using NotesShowcase.Views; */
        public class Vm { string s = "NotesShowcase.Views.MainWindow"; }
        """,
    )
    assert cli.check_flavor("csharp", cfg, tmp_path) == []


def test_csharp_adapter_exception_passes_alias_global_and_qualified(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["csharp"]
    _write(
        tmp_path / cfg["root"] / "ViewModels" / "Vm.cs",
        """\
        global using NotesShowcase.Views.Adapter;
        using B = NotesShowcase.Views.Adapter.BindableVm;
        public class Vm { object A = new NotesShowcase.Views.Adapter.BindableVm(); }
        """,
    )
    assert cli.check_flavor("csharp", cfg, tmp_path) == []


# --- TypeScript: re-exports, dynamic imports, multi-line, comments ----------


@pytest.mark.parametrize(
    "body",
    [
        'export { X } from "../views/a.js";\n',
        'export * from "../views/a.js";\n',
        'export * as ns from "../views/a.js";\n',
        'const m = import("../views/a.js");\n',
        'import "../views/a.js";\n',
        'import {\n  Alpha,\n  Beta } from "../views/a.js";\n',
    ],
    ids=[
        "re-export",
        "re-export-star",
        "re-export-namespace",
        "dynamic",
        "side-effect",
        "multi-line",
    ],
)
def test_typescript_forms_flag_viewmodel_importing_view(tmp_path: Path, body: str) -> None:
    cfg = cli.FLAVORS["typescript"]
    _write(tmp_path / cfg["root"] / "viewmodels" / "vm.ts", body)
    violations = cli.check_flavor("typescript", cfg, tmp_path)
    assert len(violations) == 1
    assert "forbidden import of views from viewmodels" in violations[0]


def test_typescript_commented_import_passes(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["typescript"]
    _write(
        tmp_path / cfg["root"] / "viewmodels" / "vm.ts",
        """\
        // import { X } from "../views/a.js";
        /* export * from "../views/b.js"; */
        /*
        import("../views/c.js");
        */
        export const ok = 1;
        """,
    )
    assert cli.check_flavor("typescript", cfg, tmp_path) == []


def test_typescript_adapter_exception_passes_and_is_anchored(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["typescript"]
    _write(
        tmp_path / cfg["root"] / "viewmodels" / "vm.ts",
        """\
        import { useX } from "../views/adapter/x.js";
        export { y } from "../views/adapter/index.js";
        """,
    )
    assert cli.check_flavor("typescript", cfg, tmp_path) == []

    _write(
        tmp_path / cfg["root"] / "viewmodels" / "vm2.ts",
        'import { z } from "../views/adapterx/z.js";\n',
    )
    violations = cli.check_flavor("typescript", cfg, tmp_path)
    assert len(violations) == 1
    assert "vm2.ts" in violations[0]


def test_typescript_violation_reports_line_of_import_statement(tmp_path: Path) -> None:
    cfg = cli.FLAVORS["typescript"]
    _write(
        tmp_path / cfg["root"] / "viewmodels" / "vm.ts",
        """\
        // header
        import {
          Alpha,
          Beta } from "../views/a.js";
        """,
    )
    violations = cli.check_flavor("typescript", cfg, tmp_path)
    assert len(violations) == 1
    assert "vm.ts:2:" in violations[0]
