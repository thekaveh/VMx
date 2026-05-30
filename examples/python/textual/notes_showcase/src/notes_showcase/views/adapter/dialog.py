"""TextualDialogService — VMx :class:`IDialogService` over Textual screens.

See scenario §7.1 (DialogService) and plan §4.b.

Phase 4.b ships the **adapter shell only** — the actual ``ConfirmModal``,
``SaveFileModal``, and ``NotifyOverlay`` widgets land in Phase 5.b under
``views/modals/``. Until then every method raises :class:`NotImplementedError`
with an explicit "Phase 5.b" pointer, mirroring the Avalonia adapter's choice
in Phase 4.a (commit ``1a25c3d`` — ``AvaloniaDialogService.Confirm``).

Why surface the type now? Composition (Phase 5.b) must wire
``IDialogService`` into the VMs before the modals exist, and the parity audits
(Phase 9) want a concrete adapter class on every flavor's bridge surface.
"""

from __future__ import annotations

from textual.app import App

from notes_showcase.viewmodels.dialog_service import IDialogService
from vmx.dialogs import FileFilter, NotificationSeverity

_PHASE_5B_MSG = (
    "TextualDialogService.{method} requires the Phase 5.b modal screen "
    "(``views/modals/`` is not built until Phase 5.b)."
)


class TextualDialogService(IDialogService):
    """Concrete :class:`IDialogService` rooted at a Textual :class:`App`.

    The constructor accepts the host app so each method can call
    ``await self._app.push_screen_wait(modal, ...)`` once the Phase 5.b modal
    classes exist. The reference is also useful for routing notifications
    through Textual's built-in ``Notification`` system if Phase 5.b chooses
    that path.
    """

    def __init__(self, app: App[object]) -> None:
        self._app = app

    async def pick_file_to_open(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
    ) -> str | None:
        raise NotImplementedError(_PHASE_5B_MSG.format(method="pick_file_to_open"))

    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        raise NotImplementedError(_PHASE_5B_MSG.format(method="pick_file_to_save"))

    async def confirm(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        raise NotImplementedError(_PHASE_5B_MSG.format(method="confirm"))

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        raise NotImplementedError(_PHASE_5B_MSG.format(method="notify"))
