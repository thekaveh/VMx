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
