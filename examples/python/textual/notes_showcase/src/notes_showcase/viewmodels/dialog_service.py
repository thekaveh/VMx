"""Re-exports for the dialog-service abstraction.

VMx ships ``DialogService`` + ``NullDialogService`` under ``vmx.dialogs``. The
showcase re-exports them under the canonical ``IDialogService`` /
``NullDialogService`` names used by the plan and the C# flavor so cross-language
audits read identically. Adapters (TextualDialogService, etc.) implement
:class:`IDialogService` in the views layer.
"""

from __future__ import annotations

from vmx import NULL_DIALOG_SERVICE, NullDialogService
from vmx.dialogs import DialogService as IDialogService

__all__ = ["NULL_DIALOG_SERVICE", "IDialogService", "NullDialogService"]
