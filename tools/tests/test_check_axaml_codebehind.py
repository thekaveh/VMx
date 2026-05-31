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
    monkeypatch.setattr(
        "sys.argv", ["check-axaml-codebehind.py", "--root", str(tmp_path)]
    )
    assert cab.main() == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_exits_one_on_violation(tmp_path: Path, monkeypatch, capsys) -> None:
    """main() returns 1 when a code-behind has disallowed content."""
    bad = (
        tmp_path
        / "examples"
        / "csharp"
        / "avalonia"
        / "Demo"
        / "Views"
        / "Bad.axaml.cs"
    )
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
    monkeypatch.setattr(
        "sys.argv", ["check-axaml-codebehind.py", "--root", str(tmp_path)]
    )
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
