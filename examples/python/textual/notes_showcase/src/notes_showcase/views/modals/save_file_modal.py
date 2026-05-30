"""SaveFileModal — path-entry dialog used by ``IDialogService.pick_file_to_save``.

The user types or accepts a suggested filename and clicks Save. The modal
dismisses with the entered string (or ``None`` on Cancel).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class SaveFileModal(ModalScreen[str | None]):
    """File-save prompt presented by :class:`TextualDialogService`."""

    DEFAULT_CSS = """
    SaveFileModal {
        align: center middle;
    }
    SaveFileModal > Vertical {
        background: $panel;
        border: solid $accent;
        padding: 1 2;
        width: 80;
        height: auto;
    }
    SaveFileModal Horizontal {
        height: auto;
        align: right middle;
    }
    SaveFileModal Button {
        margin: 1 1 0 1;
    }
    SaveFileModal Input {
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *,
        suggested_name: str | None = None,
        title: str | None = None,
    ) -> None:
        super().__init__()
        self._suggested = suggested_name or ""
        self._title = title or "Save file"

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="save_title"),
            Input(value=self._suggested, placeholder="path/to/file.json", id="path"),
            Horizontal(
                Button("Save", id="save", variant="primary"),
                Button("Cancel", id="cancel"),
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(
            (self.query_one("#path", Input).value.strip() or None)
            if event.button.id == "save"
            else None
        )
