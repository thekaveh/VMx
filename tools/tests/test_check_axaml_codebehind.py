"""Unit tests for tools/check-axaml-codebehind.py.

Pre-loaded under the underscore alias in conftest.py.
"""

import textwrap
from pathlib import Path

import check_axaml_codebehind as cab


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_check_accepts_initialize_component(tmp_path: Path) -> None:
    f = tmp_path / "MainView.axaml.cs"
    _write(
        f,
        """\
        using Avalonia.Controls;
        namespace App.Views;
        public partial class MainView : UserControl {
            public MainView() {
                InitializeComponent();
            }
        }
        """,
    )
    assert cab.check(f) == []


def test_check_accepts_avalonia_xaml_loader(tmp_path: Path) -> None:
    f = tmp_path / "MainView.axaml.cs"
    _write(
        f,
        """\
        using Avalonia.Markup.Xaml;
        public partial class MainView { public MainView() { AvaloniaXamlLoader.Load(this); } }
        """,
    )
    assert cab.check(f) == []


def test_main_exits_zero_on_empty_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    """main() returns 0 when there are no axaml.cs files to scan."""
    monkeypatch.setattr("sys.argv", ["check-axaml-codebehind.py", "--root", str(tmp_path)])
    assert cab.main() == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_exits_one_on_violation(tmp_path: Path, monkeypatch, capsys) -> None:
    """main() returns 1 when a code-behind has disallowed content."""
    bad = tmp_path / "examples" / "csharp" / "avalonia" / "Demo" / "Views" / "Bad.axaml.cs"
    _write(
        bad,
        """\
        public partial class Bad {
            public Bad() {
                InitializeComponent();
                int x = 42;
            }
        }
        """,
    )
    monkeypatch.setattr("sys.argv", ["check-axaml-codebehind.py", "--root", str(tmp_path)])
    assert cab.main() == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_check_flags_disallowed_statement(tmp_path: Path) -> None:
    f = tmp_path / "BadView.axaml.cs"
    _write(
        f,
        """\
        public partial class BadView {
            public BadView() {
                InitializeComponent();
                int x = 42;  // disallowed: business logic in code-behind
            }
        }
        """,
    )
    violations = cab.check(f)
    assert len(violations) == 1
    assert "int x = 42" in violations[0]


def test_check_flags_class_level_code_with_valid_constructor(tmp_path: Path) -> None:
    f = tmp_path / "BadView.axaml.cs"
    _write(
        f,
        """\
        using Avalonia.Controls;
        public partial class BadView {
            private readonly int _x = 42;
            public BadView() {
                InitializeComponent();
            }
        }
        """,
    )
    violations = cab.check(f)
    assert len(violations) == 1
    assert "_x = 42" in violations[0]


_VIEW_CODE_BEHIND = """\
    public partial class MainView {
        public MainView() {
            InitializeComponent();
        }
    }
    """


def _run_main(root: Path, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["check-axaml-codebehind.py", "--root", str(root)])
    code = cab.main()
    return code, capsys.readouterr().err


def test_main_flags_handler_in_second_partial_class_file(tmp_path, monkeypatch, capsys) -> None:
    """A view is a partial class, so a second file of the class can hold view logic."""
    app = tmp_path / "examples" / "csharp" / "avalonia" / "Demo"
    _write(app / "Views" / "MainView.axaml.cs", _VIEW_CODE_BEHIND)
    _write(
        app / "Views" / "MainView.Handlers.cs",
        """\
        public partial class MainView {
            private void OnClick(object sender, object e) {
                DoSomething();
            }
        }
        """,
    )
    code, err = _run_main(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "MainView.Handlers.cs" in err
    assert "DoSomething();" in err


def test_main_scans_partial_files_outside_views_folder(tmp_path, monkeypatch, capsys) -> None:
    app = tmp_path / "examples" / "csharp" / "avalonia" / "Demo"
    _write(app / "Views" / "MainView.axaml.cs", _VIEW_CODE_BEHIND)
    _write(
        app / "ViewLogic" / "MainView.Logic.cs",
        """\
        public partial class MainView {
            private int _count = 0;
        }
        """,
    )
    code, err = _run_main(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "MainView.Logic.cs" in err


def test_main_takes_partial_class_name_from_declaration(tmp_path, monkeypatch, capsys) -> None:
    app = tmp_path / "examples" / "csharp" / "avalonia" / "Demo"
    _write(app / "Views" / "Foo.axaml.cs", _VIEW_CODE_BEHIND.replace("MainView", "Bar"))
    _write(
        app / "Logic" / "Other.cs",
        """\
        public partial class Bar {
            private int _count = 0;
        }
        """,
    )
    code, err = _run_main(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "Other.cs" in err


def test_main_skips_partial_files_in_bin_obj_and_adapter(tmp_path, monkeypatch, capsys) -> None:
    app = tmp_path / "examples" / "csharp" / "avalonia" / "Demo"
    _write(app / "Views" / "MainView.axaml.cs", _VIEW_CODE_BEHIND)
    _write(
        app / "obj" / "MainView.g.cs",
        "public partial class MainView {\n    private int _generated = 1;\n}\n",
    )
    _write(
        app / "bin" / "MainView.Gen.cs",
        "public partial class MainView {\n    private int _generated = 1;\n}\n",
    )
    _write(
        app / "Views" / "Adapter" / "MainView.Bridge.cs",
        "public partial class MainView {\n    private int _bridged = 1;\n}\n",
    )
    code, err = _run_main(tmp_path, monkeypatch, capsys)
    assert code == 0, err
