"""Details panel showing properties of the selected VM node."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from vmx.components.base import _ComponentVMBase


class DetailsView(Widget):
    """Displays properties of the currently highlighted VM."""

    DEFAULT_CSS = """
    DetailsView {
        height: 1fr;
        border: solid $primary;
        padding: 1 2;
    }
    DetailsView .detail-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    """

    selected_vm: reactive[_ComponentVMBase | None] = reactive(None)
    parent_map: reactive[dict[int, str]] = reactive(dict)

    def compose(self) -> ComposeResult:
        yield Static("Node Details", classes="detail-title")
        yield Static("", id="detail-content")

    def watch_selected_vm(self, vm: _ComponentVMBase | None) -> None:
        content = self.query_one("#detail-content", Static)
        if vm is None:
            content.update("(no node selected)")
            return

        parent_name = self.parent_map.get(id(vm), "—")

        lines = [
            f"[bold]name:[/bold]           {vm.name}",
            f"[bold]type:[/bold]           {vm.type.value}",
            f"[bold]status:[/bold]         {vm.status.name}",
            f"[bold]is_constructed:[/bold] {vm.is_constructed}",
            f"[bold]is_current:[/bold]     {vm.is_current}",
            f"[bold]parent:[/bold]         {parent_name}",
        ]
        content.update("\n".join(lines))
