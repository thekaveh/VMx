"""Unit tests for tools/check-textual-views.py."""

import textwrap
from pathlib import Path

import check_textual_views as ctv


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_check_accepts_allowed_methods(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def __init__(self): super().__init__()
            def compose(self): yield Widget()
            def on_mount(self): self._wire_bindings()
            def action_save(self) -> None: self.save_command.execute()
            def on_button_pressed(self, event) -> None: self.action_save()
        """,
    )
    assert ctv.check_module(f) == []


def test_main_exits_zero_on_empty_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["check-textual-views.py", "--root", str(tmp_path)])
    assert ctv.main() == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_exits_one_on_violation(tmp_path: Path, monkeypatch, capsys) -> None:
    bad = (
        tmp_path / "examples" / "python" / "textual" / "demo" / "src" / "demo" / "views" / "bad.py"
    )
    _write(
        bad,
        """\
        from textual.widget import Widget
        class Bad(Widget):
            def _compute(self): return 42
        """,
    )
    monkeypatch.setattr("sys.argv", ["check-textual-views.py", "--root", str(tmp_path)])
    assert ctv.main() == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_check_flags_disallowed_method(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def __init__(self): super().__init__()
            def compose(self): yield Widget()
            def _compute_thing(self): return 42  # disallowed: business logic
        """,
    )
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "_compute_thing" in violations[0]


def test_hub_rule_flags_direct_subscription_with_statement_line(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_mount(self):
                x = 1
                self._sub = self._vm.hub.messages.subscribe(print)
        """,
    )
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "subscribes to the hub" in violations[0]
    # The reported line is the offending statement, not the method def.
    assert ":5:" in violations[0]


def test_hub_rule_is_word_anchored_not_substring(tmp_path: Path) -> None:
    """`github.subscribe(...)` must not trip the hub rule; `theme_hub` must."""
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_mount(self):
                self._sub = self.github.events.subscribe(print)
        """,
    )
    assert ctv.check_module(f) == []

    g = tmp_path / "view2.py"
    _write(
        g,
        """\
        from textual.widget import Widget
        class MyView2(Widget):
            def on_mount(self):
                self._sub = self.theme_hub.messages.subscribe(print)
        """,
    )
    violations = ctv.check_module(g)
    assert len(violations) == 1
