"""Scrolling DataTable of recent hub messages."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

from vmx.messages import ConstructionStatusChangedMessage, PropertyChangedMessage
from vmx.messages.protocols import Message


class MessageLog(Widget):
    """Scrolling table that appends every hub message as a row."""

    DEFAULT_CSS = """
    MessageLog {
        height: 1fr;
        border: solid $primary;
    }
    MessageLog Label {
        text-style: bold;
        color: $accent;
        padding: 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Hub Messages")
        table: DataTable[str] = DataTable(id="msg-table")
        table.cursor_type = "none"
        yield table

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Sender", "Type", "Detail")

    def append_message(self, msg: Message) -> None:
        table = self.query_one(DataTable)
        ts = datetime.now().strftime("%H:%M:%S")
        msg_type = type(msg).__name__

        detail: str
        if isinstance(msg, PropertyChangedMessage):
            detail = msg.property_name
        elif isinstance(msg, ConstructionStatusChangedMessage):
            detail = msg.status.name
        else:
            detail = ""

        table.add_row(ts, msg.sender_name, msg_type, detail)
        table.scroll_end(animate=False)
