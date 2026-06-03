"""Unit tests for :mod:`notes_showcase.views.adapter.dialog`.

Closes the coverage gap on :class:`TextualDialogService` — the modal-bound
async methods were exercised end-to-end via the smoke test but not as
individual VM-layer units. Tests here drive each method against a mocked
:class:`textual.app.App` and verify both the modal argument shape and the
NotImplementedError on the deliberately un-wired ``pick_file_to_open`` path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from notes_showcase.views.adapter.dialog import TextualDialogService
from notes_showcase.views.modals.confirm_modal import ConfirmModal
from notes_showcase.views.modals.notify_modal import NotifyModal
from notes_showcase.views.modals.save_file_modal import SaveFileModal
from vmx.dialogs import NotificationSeverity


def _make_app(return_value: Any = None) -> MagicMock:
    app = MagicMock()
    app.push_screen_wait = AsyncMock(return_value=return_value)
    return app


def test_constructor_retains_app_reference() -> None:
    app = _make_app()
    service = TextualDialogService(app)
    assert service._app is app


@pytest.mark.asyncio
async def test_pick_file_to_open_raises_not_implemented() -> None:
    service = TextualDialogService(_make_app())
    with pytest.raises(NotImplementedError):
        await service.pick_file_to_open()


@pytest.mark.asyncio
async def test_pick_file_to_save_pushes_save_modal_and_returns_path() -> None:
    app = _make_app(return_value="/tmp/out.json")
    service = TextualDialogService(app)

    result = await service.pick_file_to_save(suggested_name="out.json", title="Export")

    assert result == "/tmp/out.json"
    app.push_screen_wait.assert_awaited_once()
    (modal,), _ = app.push_screen_wait.call_args
    assert isinstance(modal, SaveFileModal)


@pytest.mark.asyncio
async def test_confirm_pushes_confirm_modal_and_returns_result() -> None:
    app = _make_app(return_value=True)
    service = TextualDialogService(app)

    result = await service.confirm("Delete?", title="Confirm")

    assert result is True
    (modal,), _ = app.push_screen_wait.call_args
    assert isinstance(modal, ConfirmModal)


@pytest.mark.asyncio
async def test_notify_pushes_notify_modal_with_severity() -> None:
    app = _make_app()
    service = TextualDialogService(app)

    await service.notify(
        "saved",
        title="OK",
        severity=NotificationSeverity.WARNING,
    )

    (modal,), _ = app.push_screen_wait.call_args
    assert isinstance(modal, NotifyModal)
