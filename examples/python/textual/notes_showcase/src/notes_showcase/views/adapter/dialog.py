"""TextualDialogService — VMx :class:`IDialogService` over Textual screens.

See scenario §7.1 (DialogService) and plan §4.b / 5.b.

Phase 5.b completes the adapter: every method drives a real
:class:`~textual.screen.ModalScreen` defined under
``notes_showcase.views.modals``. The file-open path stays at
:class:`NotImplementedError` because the showcase scenario only requires
file-save (see ``WorkspaceVM._export_internal``); wiring a load-flow is a
Phase 7 polish item.
"""

from __future__ import annotations

from typing import Any

from textual.app import App

from notes_showcase.viewmodels.dialog_service import IDialogService
from notes_showcase.views.modals.confirm_modal import ConfirmModal
from notes_showcase.views.modals.notify_modal import NotifyModal
from notes_showcase.views.modals.save_file_modal import SaveFileModal
from vmx.dialogs import FileFilter, NotificationSeverity


class TextualDialogService(IDialogService):
    """Concrete :class:`IDialogService` rooted at a Textual :class:`App`.

    The constructor accepts the host app so each method can call
    ``await self._app.push_screen_wait(modal, ...)``.
    """

    def __init__(self, app: App[Any]) -> None:
        self._app = app

    async def pick_file_to_open(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
    ) -> str | None:
        # Not exercised by the notes-showcase flow; export is save-only.
        raise NotImplementedError(
            "TextualDialogService.pick_file_to_open is not wired in Phase 5.b "
            "(showcase scenario only requires save). Polish item for Phase 7."
        )

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        return await self._app.push_screen_wait(
            SaveFileModal(suggested_name=suggested_name, title=title)
        )

    async def confirm(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        return await self._app.push_screen_wait(ConfirmModal(message, title=title))

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        await self._app.push_screen_wait(
            NotifyModal(message, title=title, severity=severity)
        )
