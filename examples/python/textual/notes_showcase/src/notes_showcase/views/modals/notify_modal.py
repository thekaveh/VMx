"""NotifyModal — severity-tagged "OK" message used by ``IDialogService.notify``.

Auto-styled by severity (info / warning / error). Dismisses with ``None`` on
acknowledgement.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from vmx.dialogs import NotificationSeverity


class NotifyModal(ModalScreen[None]):
    """Severity-styled notification overlay."""

    DEFAULT_CSS = """
    NotifyModal {
        align: center middle;
    }
    NotifyModal > Vertical {
        background: $panel;
        border: solid $accent;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    NotifyModal.-warning > Vertical {
        border: solid $warning;
    }
    NotifyModal.-error > Vertical {
        border: solid $error;
    }
    NotifyModal Horizontal {
        height: auto;
        align: center middle;
    }
    """

    def __init__(
        self,
        message: str,
        *,
        title: str | None = None,
        severity: NotificationSeverity = NotificationSeverity.INFO,
    ) -> None:
        super().__init__()
        self._message = message
        self._title = title or "Notification"
        self._severity = severity

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="notify_title"),
            Label(self._message, id="notify_message"),
            Horizontal(Button("OK", id="ok", variant="primary")),
        )

    def on_mount(self) -> None:
        self.add_class(f"-{self._severity.value}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
