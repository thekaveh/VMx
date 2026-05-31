"""ConfirmModal — Yes/No confirmation prompt used by ``IDialogService.confirm``.

Returns ``True`` when the user picks Yes, ``False`` for No or any dismissal.
Per spec §6.1 the widget class only owns ``compose()`` / ``on_mount()`` /
``action_*()``; the button handler delegates to a single-statement action.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmModal(ModalScreen[bool]):
    """Confirmation dialog presented by :class:`TextualDialogService`."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        background: $panel;
        border: solid $accent;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    ConfirmModal Horizontal {
        height: auto;
        align: center middle;
    }
    ConfirmModal Button {
        margin: 1 1 0 1;
    }
    """

    def __init__(self, message: str, *, title: str | None = None) -> None:
        super().__init__()
        self._message = message
        self._title = title or "Confirm"

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="confirm_title"),
            Label(self._message, id="confirm_message"),
            Horizontal(
                Button("Yes", id="yes", variant="primary"),
                Button("No", id="no"),
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")
