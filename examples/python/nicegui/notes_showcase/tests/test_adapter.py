"""One test per adapter bridge, each on a NiceGUI page in the user simulation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from nicegui import ui
from nicegui.testing.user_notify import UserNotify
from nicegui.testing.user_simulation import user_simulation
from reactivex.abc import DisposableBase
from reactivex.subject import BehaviorSubject, Subject
from vmx import (
    AsyncRelayCommand,
    ComponentVMOf,
    Message,
    MessageHub,
    ObservableList,
    PropertyChangedMessage,
    RelayCommand,
    RxDispatcher,
)
from vmx.properties.derived import from_one

from nicegui_notes.adapter import (
    bind_command,
    bind_derived_property,
    bind_property,
    bind_property_two_way,
    bind_refreshable,
    release_on_delete,
    text,
)


@dataclass(frozen=True)
class Note:
    title: str


def _vm(hub: MessageHub[Message], model: object) -> ComponentVMOf[object]:
    vm = (
        ComponentVMOf[object]
        .builder()
        .name("vm")
        .model(model)
        .services(hub, RxDispatcher.immediate())
        .build()
    )
    vm.construct()
    return vm


def _model_changes(hub: MessageHub[Message]) -> list[object]:
    changes: list[object] = []
    hub.messages.subscribe(
        lambda m: (
            changes.append(m)
            if isinstance(m, PropertyChangedMessage) and m.property_name == "model"
            else None
        )
    )
    return changes


async def test_bind_property_shows_the_value_and_follows_changes() -> None:
    vm = _vm(MessageHub[Message](), Note("draft"))

    def page() -> None:
        label = ui.label().mark("title")
        release_on_delete(bind_property(label, "text", vm, "model", lambda note: note.title))

    async with user_simulation(page) as user:
        await user.open("/")
        await user.should_see("draft")
        vm.model = Note("renamed")
        await user.should_see("renamed")
        await user.should_not_see("draft")


async def test_bind_property_two_way_carries_each_change_once_in_each_direction() -> None:
    hub = MessageHub[Message]()
    vm = _vm(hub, "from vm")
    changes = _model_changes(hub)

    def page() -> None:
        field = ui.input("Title").mark("field")
        release_on_delete(bind_property_two_way(field, vm, "model", text))

    async with user_simulation(page) as user:
        await user.open("/")
        field = user.find(marker="field")
        assert {element.value for element in field.elements} == {"from vm"}

        field.clear()
        assert vm.model == ""  # a cleared input reports None; text() parses it
        field.type("typed")
        assert vm.model == "typed"

        vm.model = "set by the vm"
        await user.should_see("set by the vm")

    # One for clear(), one for type(), one from the VM; none echoed back.
    assert len(changes) == 3


async def test_bind_derived_property_follows_its_sources() -> None:
    source = BehaviorSubject("quiet")
    derived = from_one(source, transform=str.upper)

    def page() -> None:
        label = ui.label().mark("derived")
        release_on_delete(bind_derived_property(label, "text", derived))

    async with user_simulation(page) as user:
        await user.open("/")
        await user.should_see("QUIET")
        source.on_next("loud")
        await user.should_see("LOUD")


async def test_bind_command_runs_it_and_follows_can_execute() -> None:
    state = {"ready": False, "runs": 0}
    ready_changed: Subject[object] = Subject()
    command = (
        RelayCommand.builder()
        .predicate(lambda: state["ready"])
        .task(lambda: state.__setitem__("runs", state["runs"] + 1))
        .triggers(ready_changed)
        .build()
    )

    def page() -> None:
        button = ui.button("Run").mark("run")
        release_on_delete(bind_command(button, command))

    async with user_simulation(page) as user:
        await user.open("/")
        button = user.find(marker="run")
        assert [element.enabled for element in button.elements] == [False]
        button.click()  # a disabled button ignores the click
        assert state["runs"] == 0

        state["ready"] = True
        ready_changed.on_next(None)
        assert [element.enabled for element in button.elements] == [True]
        button.click()

    assert state["runs"] == 1


def _record_notifications(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    """The user simulation's ``ui.notify`` drops its keyword arguments; keep the type."""
    notifications: list[tuple[str, object]] = []
    original = UserNotify.__call__

    def record(self: UserNotify, message: str, **kwargs: object) -> None:
        notifications.append((message, kwargs.get("type")))
        original(self, message, **kwargs)

    monkeypatch.setattr(UserNotify, "__call__", record)
    return notifications


def _failing_command() -> AsyncRelayCommand:
    async def fail() -> None:
        raise OSError("disk full")

    return AsyncRelayCommand.builder().task(fail).build()


async def _settle(done: Callable[[], object]) -> None:
    for _ in range(100):
        if done():
            return
        await asyncio.sleep(0.01)


async def test_bind_command_shows_a_failure_in_a_negative_notification(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # #794: an AsyncRelayCommand reports a fire-and-forget failure on errors.
    notifications = _record_notifications(monkeypatch)
    command = _failing_command()

    def page() -> None:
        button = ui.button("Save").mark("save")
        release_on_delete(bind_command(button, command))

    with caplog.at_level(logging.ERROR, logger="nicegui_notes.adapter.binding"):
        async with user_simulation(page) as user:
            await user.open("/")
            user.find(marker="save").click()
            await _settle(lambda: notifications)

    assert notifications == [("Command failed: disk full", "negative")]
    records = [
        record
        for record in caplog.records
        if record.name == "nicegui_notes.adapter.binding" and record.exc_info
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert isinstance(records[0].exc_info[1] if records[0].exc_info else None, OSError)


async def test_a_released_command_binding_shows_no_later_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    notifications = _record_notifications(monkeypatch)
    command = _failing_command()
    bindings: list[DisposableBase] = []

    def page() -> None:
        button = ui.button("Save").mark("save")
        bindings.append(bind_command(button, command))

    with caplog.at_level(logging.ERROR, logger="nicegui_notes.adapter.binding"):
        async with user_simulation(page) as user:
            await user.open("/")
            bindings[0].dispose()
            command.execute()
            await _settle(lambda: not command.is_executing)
            await asyncio.sleep(0.05)

    assert notifications == []
    assert [record for record in caplog.records if record.exc_info] == []


async def test_bind_derived_property_accepts_a_property_without_a_first_value() -> None:
    # #794: the first value arrives without a value_changed emission.
    source: Subject[str] = Subject()
    derived = from_one(source, transform=str.upper)

    def page() -> None:
        label = ui.label().mark("derived")
        release_on_delete(bind_derived_property(label, "text", derived))

    async with user_simulation(page) as user:
        await user.open("/")
        source.on_next("first")
        source.on_next("second")
        await user.should_see("SECOND")


async def test_bind_refreshable_rebuilds_the_collection() -> None:
    items: ObservableList[str] = ObservableList()
    items.append("first")

    def page() -> None:
        @ui.refreshable
        def rows() -> None:
            for item in items:
                ui.label(item)

        rows()
        release_on_delete(bind_refreshable(rows, items.on_property_changed))

    async with user_simulation(page) as user:
        await user.open("/")
        await user.should_see("first")
        items.append("second")
        await user.should_see("second")
        items.remove("first")
        await user.should_not_see("first")
