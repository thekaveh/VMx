from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from reactivex.abc import DisposableBase
from textual.app import RenderResult
from textual.binding import Binding, BindingType
from textual.message import Message as TextualMessage
from textual.reactive import reactive
from textual.widget import Widget
from vmx import ComponentVMOf, RelayCommand


@dataclass
class Note:
    title: str


class NoteWidget(Widget, can_focus=True):
    """Shows a borrowed note VM; whoever created the VM constructs and disposes it."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("s", "save", "Save")]

    title: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("")

    class VmChanged(TextualMessage):
        """Carries one VM-local property change onto the App thread."""

        def __init__(self, property_name: str) -> None:
            super().__init__()
            self.property_name = property_name

    def __init__(self, vm: ComponentVMOf[Note], save_command: RelayCommand) -> None:
        super().__init__()
        self._vm = vm
        self._save_command = save_command
        self._subscription: DisposableBase | None = None

    def on_mount(self) -> None:
        # `property_changed` is the VM-local stream: it carries `model`
        # assignments and every lifecycle `status` change, on the thread that
        # made the change. `post_message` is thread-safe and queues each change
        # for this widget on the App thread.
        self._subscription = self._vm.property_changed.subscribe(self._forward)
        # Read after subscribing, so a change in between is not lost.
        self._show("model")
        self._show("status")

    def _forward(self, property_name: str) -> None:
        self.post_message(self.VmChanged(property_name))

    def on_note_widget_vm_changed(self, message: NoteWidget.VmChanged) -> None:
        self._show(message.property_name)

    def _show(self, property_name: str) -> None:
        if property_name == "model":
            self.title = self._vm.model.title
        elif property_name == "status":
            self.status_text = self._vm.status.name

    def render(self) -> RenderResult:
        return f"{self.title} · {self.status_text}"

    def action_save(self) -> None:
        self._save_command.execute(None)

    def on_unmount(self) -> None:
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
