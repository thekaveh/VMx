"""IDialogService contract (chapter 19, ADR-0029).

Host-side modal interaction contract: file pick, confirm prompt, and
severity-tagged notify. See spec/19-dialogs.md and ADR-0029.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class NotificationSeverity(Enum):
    """Severity level for a notification presented via :meth:`DialogService.notify`."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class FileFilter:
    """Describes a file-type filter for file-picker dialogs.

    Args:
        description: Human-readable label, e.g. ``"Image files"``.
        extensions: File extension patterns, e.g. ``["*.png", "*.jpg"]``.
    """

    description: str
    extensions: Sequence[str]


class DialogService(ABC):
    """Abstract base for host-side modal interactions. See ADR-0029.

    Implementers provide host-specific dialogs (WPF, Avalonia, console, test).
    Use :class:`~vmx.dialogs.NullDialogService` in tests and headless environments.
    """

    @abstractmethod
    async def pick_file_to_open(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
    ) -> str | None:
        """Present a file-open dialog.

        Returns the selected path as a string, or ``None`` if the user cancels.
        All parameters are optional.
        """
        ...

    @abstractmethod
    async def pick_file_to_save(
        self,
        filter: FileFilter | None = None,
        title: str | None = None,
        suggested_name: str | None = None,
    ) -> str | None:
        """Present a file-save dialog.

        Returns the selected path, or ``None`` on cancel.
        All parameters are optional.
        """
        ...

    @abstractmethod
    async def confirm(
        self,
        message: str,
        title: str | None = None,
    ) -> bool:
        """Present a confirmation prompt.

        Returns ``True`` when confirmed, ``False`` when cancelled or dismissed.
        """
        ...

    @abstractmethod
    async def notify(
        self,
        message: str,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        """Present a notification with the given severity.

        Returns when acknowledged or dismissed. Severity defaults to
        :attr:`~NotificationSeverity.INFO` when not supplied.
        """
        ...
