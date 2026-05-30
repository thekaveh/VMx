"""Modal screens used by :class:`TextualDialogService` (scenario §7.1).

Each modal is a thin :class:`textual.screen.ModalScreen` that gathers a value
(``bool`` for confirm, ``str`` for save-file, ``None`` for notify) and
dismisses with it; the dialog-service ``await``\\s on
:meth:`textual.app.App.push_screen_wait` to receive the result.
"""

from __future__ import annotations

from notes_showcase.views.modals.confirm_modal import ConfirmModal
from notes_showcase.views.modals.notify_modal import NotifyModal
from notes_showcase.views.modals.save_file_modal import SaveFileModal

__all__ = ["ConfirmModal", "NotifyModal", "SaveFileModal"]
