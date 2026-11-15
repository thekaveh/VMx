"""Unit tests for tools/check-textual-views.py."""

import textwrap
from pathlib import Path

import check_textual_views as ctv
import pytest


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _widget_module(path: Path, method_src: str) -> None:
    """Write a Widget class whose single method is ``method_src`` (already dedented)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "from textual.widget import Widget\nclass MyView(Widget):\n"
    path.write_text(body + textwrap.indent(textwrap.dedent(method_src), "    "), encoding="utf-8")


# --- hub subscription forms -------------------------------------------------


@pytest.mark.parametrize(
    "stmts",
    [
        "self._subs.append(self._vm.hub.messages.subscribe(cb))",
        "self._vm.hub.messages.pipe(f).subscribe(cb)",
        "messages = self._vm.hub.messages\nmessages.subscribe(cb)",
        "resolve_hub(self._vm).messages.subscribe(cb)",
    ],
    ids=["nested-call-argument", "pipe-chain", "local-alias", "resolve-hub-call"],
)
def test_hub_rule_flags_subscription_forms(tmp_path: Path, stmts: str) -> None:
    f = tmp_path / "view.py"
    method = "def on_mount(self):\n" + textwrap.indent(stmts, "    ") + "\n"
    _widget_module(f, method)
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "subscribes to the hub" in violations[0]


def test_hub_rule_flags_subscription_nested_in_guarded_handler(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _widget_module(
        f,
        """\
        def on_button_pressed(self, event) -> None:
            if event.button.id:
                self._subs.append(self._vm.hub.messages.subscribe(cb))
        """,
    )
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "subscribes to the hub" in violations[0]


# --- statements inside compound blocks count toward the thin-handler limit ---


_COMPOUND_HANDLERS = [
    pytest.param(
        """\
        def on_button_pressed(self, event) -> None:
            with self._lock:
                self.a()
                self.b()
                self.c()
        """,
        3,
        id="with",
    ),
    pytest.param(
        """\
        async def on_button_pressed(self, event) -> None:
            async with self._lock:
                self.a()
                self.b()
                self.c()
        """,
        3,
        id="async-with",
    ),
    pytest.param(
        """\
        def on_button_pressed(self, event) -> None:
            for item in self._items:
                self.a(item)
                self.b(item)
                self.c(item)
        """,
        3,
        id="for",
    ),
    pytest.param(
        """\
        async def on_button_pressed(self, event) -> None:
            async for item in self._stream:
                self.a(item)
                self.b(item)
                self.c(item)
        """,
        3,
        id="async-for",
    ),
    pytest.param(
        """\
        def on_button_pressed(self, event) -> None:
            while self._pending:
                self.a()
                self.b()
                self.c()
        """,
        3,
        id="while",
    ),
    pytest.param(
        """\
        def on_button_pressed(self, event) -> None:
            try:
                self.a()
                self.b()
                self.c()
            except ValueError:
                self.d()
        """,
        4,
        id="try-body-and-except",
    ),
    pytest.param(
        """\
        def on_button_pressed(self, event) -> None:
            match event.button.id:
                case "save":
                    self.a()
                    self.b()
                    self.c()
        """,
        3,
        id="match",
    ),
]


@pytest.mark.parametrize(("handler_src", "count"), _COMPOUND_HANDLERS)
def test_handler_statements_inside_compound_blocks_are_counted(
    tmp_path: Path, handler_src: str, count: int
) -> None:
    f = tmp_path / "view.py"
    _widget_module(f, handler_src)
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert f"has {count} statements" in violations[0]
    assert "max 1 for on_* event handlers" in violations[0]


def test_single_call_inside_compound_block_still_counts_as_one(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _widget_module(
        f,
        """\
        def on_button_pressed(self, event) -> None:
            with self._lock:
                self.save_command.execute()
        """,
    )
    assert ctv.check_module(f) == []


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


def test_check_accepts_single_guarded_event_statement(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_button_pressed(self, event) -> None:
                if event.button.id == "save":
                    self.save_command.execute()
        """,
    )
    assert ctv.check_module(f) == []


def test_check_treats_on_unmount_as_lifecycle(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_unmount(self) -> None:
                self._disposables.dispose()
                self._closed = True
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


def test_nested_on_handler_body_counts_real_statements(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_button_pressed(self, event) -> None:
                if event.button.id == "save":
                    self.save_command.execute()
                    self.status = "saved"
        """,
    )
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "max 1" in violations[0]


def test_nested_on_handler_hub_subscription_is_flagged(tmp_path: Path) -> None:
    f = tmp_path / "view.py"
    _write(
        f,
        """\
        from textual.widget import Widget
        class MyView(Widget):
            def on_button_pressed(self, event) -> None:
                if event.button.id == "save":
                    self._sub = self._vm.hub.messages.subscribe(print)
        """,
    )
    violations = ctv.check_module(f)
    assert len(violations) == 1
    assert "subscribes to the hub" in violations[0]
