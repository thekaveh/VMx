"""NullDialogService — null-object implementation per ADR-0017.

See spec/19-dialogs.md §3 and ADR-0017.
"""

from __future__ import annotations

from vmx.dialogs.dialog_service import DialogService, FileFilter, NotificationSeverity


class NullDialogService(DialogService):
    """Stateless null-object dialog service.

    All methods return the safest default:

    - :meth:`pick_file_to_open` → ``None`` (no host available; treat as cancel)
    - :meth:`pick_file_to_save` → ``None``
    - :meth:`confirm` → ``False`` (avoids triggering destructive operations)
    - :meth:`notify` → no-op

    Stateless and safe to share via :data:`NULL_DIALOG_SERVICE`.
    """

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
        return None

    async def confirm(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        return False

    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        return None


NULL_DIALOG_SERVICE: NullDialogService = NullDialogService()
"""Shared singleton instance (the service holds no state)."""
