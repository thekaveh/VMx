"""Executes the Textual integration recipe on a running Textual App.

``textual_recipe.py`` is the exact code shown in
docs/content/integration/textual.md; tools/tests/test_host_recipe_sync.py keeps
the two identical. No conformance-ID markers (integration recipe).
"""

from __future__ import annotations

import threading

from textual.app import App, ComposeResult
from vmx import (
    ComponentVMOf,
    ConstructionStatus,
    Message,
    MessageHub,
    PropertyChangedMessage,
    RelayCommand,
    RxDispatcher,
)

from tests.views.textual_recipe import Note, NoteWidget


class RecordingNoteWidget(NoteWidget):
    """Records what reaches the widget and the thread each update ran on."""

    def __init__(self, vm: ComponentVMOf[Note], save_command: RelayCommand) -> None:
        super().__init__(vm, save_command)
        self.changes: list[str] = []
        self.statuses: list[str] = []
        self.title_threads: list[int] = []

    def on_note_widget_vm_changed(self, message: NoteWidget.VmChanged) -> None:
        self.changes.append(message.property_name)
        super().on_note_widget_vm_changed(message)

    def watch_status_text(self, value: str) -> None:
        self.statuses.append(value)

    def watch_title(self, value: str) -> None:
        self.title_threads.append(threading.get_ident())


class RecipeApp(App[None]):
    def __init__(self, widget: NoteWidget) -> None:
        super().__init__()
        self.widget = widget
        self.thread_id = 0

    def compose(self) -> ComposeResult:
        yield self.widget

    def on_mount(self) -> None:
        self.thread_id = threading.get_ident()


def _vm(hub: MessageHub[Message], *, construct: bool = True) -> ComponentVMOf[Note]:
    vm = (
        ComponentVMOf[Note]
        .builder()
        .name("note")
        .model(Note("draft"))
        .services(hub, RxDispatcher.immediate())
        .build()
    )
    if construct:
        vm.construct()
    return vm


def _command() -> tuple[RelayCommand, list[None]]:
    runs: list[None] = []
    return RelayCommand.builder().task(lambda: runs.append(None)).build(), runs


def _observer_count(vm: ComponentVMOf[Note]) -> int:
    # The VM-local subject is private; counting its observers is the only
    # direct way to prove the adapter left no subscription behind.
    return len(vm._property_changed_subject.observers)


async def test_title_and_status_are_shown_right_after_mount() -> None:
    vm = _vm(MessageHub[Message]())
    widget = NoteWidget(vm, _command()[0])

    async with RecipeApp(widget).run_test():
        assert widget.title == "draft"
        assert widget.status_text == "CONSTRUCTED"
        assert str(widget.render()) == "draft · CONSTRUCTED"


async def test_lifecycle_reaches_the_widget_through_the_local_status_notification() -> None:
    hub = MessageHub[Message]()
    hub_property_names: list[str] = []
    hub.messages.subscribe(
        lambda m: (
            hub_property_names.append(m.property_name)
            if isinstance(m, PropertyChangedMessage)
            else None
        )
    )
    vm = _vm(hub, construct=False)
    widget = RecordingNoteWidget(vm, _command()[0])

    async with RecipeApp(widget).run_test() as pilot:
        assert widget.status_text == "DESTRUCTED"  # the initial status
        vm.construct()
        await pilot.pause()
        assert widget.status_text == "CONSTRUCTED"
        vm.destruct()
        await pilot.pause()
        assert widget.status_text == "DESTRUCTED"
        vm.dispose()
        await pilot.pause()
        assert widget.status_text == "DISPOSED"

    # Each handled message re-reads the VM, so a transient status that is
    # already over when the App thread handles it is shown as the current one.
    assert widget.statuses == ["", "DESTRUCTED", "CONSTRUCTED", "DESTRUCTED", "DISPOSED"]
    # Two local notifications each for construct and destruct, one for dispose.
    assert widget.changes.count("status") == 5
    assert "status" not in hub_property_names


async def test_each_model_assignment_reaches_the_widget_once() -> None:
    vm = _vm(MessageHub[Message]())
    widget = RecordingNoteWidget(vm, _command()[0])

    async with RecipeApp(widget).run_test() as pilot:
        vm.model = Note("first")
        vm.model = Note("second")
        await pilot.pause()

        assert widget.changes == ["model", "model"]
        assert widget.title == "second"


async def test_a_worker_thread_change_is_applied_on_the_app_thread() -> None:
    vm = _vm(MessageHub[Message]())
    widget = RecordingNoteWidget(vm, _command()[0])
    app = RecipeApp(widget)

    async with app.run_test() as pilot:
        worker = threading.Thread(target=lambda: setattr(vm, "model", Note("from worker")))
        worker.start()
        worker.join()
        await pilot.pause()

        assert widget.title == "from worker"
        assert worker.ident not in widget.title_threads
        assert set(widget.title_threads) == {app.thread_id}


async def test_unmount_releases_the_subscription_and_leaves_the_vm_to_its_owner() -> None:
    vm = _vm(MessageHub[Message]())
    widget = NoteWidget(vm, _command()[0])

    async with RecipeApp(widget).run_test() as pilot:
        assert _observer_count(vm) == 1
        await widget.remove()
        await pilot.pause()

        assert _observer_count(vm) == 0
        assert vm.status is ConstructionStatus.CONSTRUCTED

    assert vm.status is ConstructionStatus.CONSTRUCTED


async def test_save_runs_the_supplied_command() -> None:
    command, runs = _command()
    widget = NoteWidget(_vm(MessageHub[Message]()), command)

    async with RecipeApp(widget).run_test() as pilot:
        widget.focus()
        await pilot.press("s")

    assert runs == [None]
