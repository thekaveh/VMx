"""TextualDialogService — VMx :class:`IDialogService` over Textual screens.

Every operation required by the save-only showcase scenario drives a real
:class:`~textual.screen.ModalScreen` defined under
``notes_showcase.views.modals``. The scenario has no load flow, so file-open
returns the contract's safe cancellation result. Export uses file-save through
``WorkspaceVM._export_internal``.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from textual.app import App
from textual.screen import ModalScreen
from vmx.dialogs import FileFilter, NotificationSeverity

from notes_showcase.viewmodels.dialog_service import IDialogService
from notes_showcase.views.modals.confirm_modal import ConfirmModal
from notes_showcase.views.modals.notify_modal import NotifyModal
from notes_showcase.views.modals.save_file_modal import SaveFileModal

_ResultT = TypeVar("_ResultT")


class TextualDialogService(IDialogService):
    """Concrete :class:`IDialogService` rooted at a Textual :class:`App`.

    The constructor accepts the host app. Each method pushes a modal and
    awaits its dismissal through a callback. ``push_screen_wait`` is not used:
    Textual allows it only inside a worker, and commands call these methods
    from ordinary tasks.
    """

    def __init__(self, app: App[Any]) -> None:
        self._app = app

    async def _show(self, screen: ModalScreen[_ResultT]) -> _ResultT | None:
        result: asyncio.Future[_ResultT | None] = asyncio.get_running_loop().create_future()

        def dismissed(value: _ResultT | None) -> None:
            if not result.done():
                result.set_result(value)

        await self._app.push_screen(screen, callback=dismissed)
        return await result

    async def pick_file_to_open(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
    ) -> str | None:
        return None

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return await self._show(SaveFileModal(suggested_name=suggested_name, title=title))

    async def confirm(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        confirmed = await self._show(ConfirmModal(message, title=title))
        return confirmed is True

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        await self._show(NotifyModal(message, title=title, severity=severity))
