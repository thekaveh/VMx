"""Unit tests for :mod:`notes_showcase.views.app`.

Each ``action_*`` method on :class:`NotesShowcaseApp` is a single-line
delegation to the bound :class:`WorkspaceVM` (per spec §6.1). The smoke
test covers ``compose`` + mount; these tests cover the keybinding dispatch
edges so coverage doesn't depend on a user actually pressing every chord.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from notes_showcase.views.app import NotesShowcaseApp


def _make_app() -> tuple[NotesShowcaseApp, MagicMock]:
    workspace = MagicMock()
    app = NotesShowcaseApp(workspace)
    return app, workspace


@pytest.mark.asyncio
async def test_action_save_executes_note_form_approve() -> None:
    app, workspace = _make_app()
    await app.action_save()
    workspace.note_form.approve_command.execute.assert_called_once_with()


@pytest.mark.asyncio
async def test_action_new_note_executes_command() -> None:
    app, workspace = _make_app()
    await app.action_new_note()
    workspace.new_note_command.execute.assert_called_once_with()


@pytest.mark.asyncio
async def test_action_new_notebook_executes_command() -> None:
    app, workspace = _make_app()
    await app.action_new_notebook()
    workspace.new_notebook_command.execute.assert_called_once_with()


@pytest.mark.asyncio
async def test_action_export_executes_command() -> None:
    app, workspace = _make_app()
    await app.action_export()
    workspace.export_command.execute.assert_called_once_with()


@pytest.mark.asyncio
async def test_action_focus_search_queries_and_focuses_search_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # action_focus_search runs `self.query_one("#search_input", Input).focus()`.
    # Mounting the full app needs a wired VM tree (notebooks_tree / notes_list
    # bind at on_mount); patch query_one to keep this a viewmodel-layer unit
    # test rather than a widget integration test.
    app, _workspace = _make_app()
    focused: list[str] = []

    class _FakeInput:
        def focus(self) -> None:
            focused.append("ok")

    monkeypatch.setattr(app, "query_one", lambda *_args, **_kw: _FakeInput())

    await app.action_focus_search()
    assert focused == ["ok"]
