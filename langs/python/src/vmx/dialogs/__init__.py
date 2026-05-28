"""IDialogService (chapter 19, ADR-0029).

Host-side service contract for modal interactions: file pick, confirm prompt,
and severity-tagged notify. See spec/19-dialogs.md.
"""

from vmx.dialogs.dialog_service import DialogService, FileFilter, NotificationSeverity
from vmx.dialogs.null_dialog_service import NULL_DIALOG_SERVICE, NullDialogService

__all__ = [
    "NULL_DIALOG_SERVICE",
    "DialogService",
    "FileFilter",
    "NotificationSeverity",
    "NullDialogService",
]
