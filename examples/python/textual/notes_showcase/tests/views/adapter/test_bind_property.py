"""Unit tests for :func:`notes_showcase.views.adapter.bind_property` (plan §4.b)."""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Static

from vmx import MessageHub
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message

from notes_showcase.views.adapter import bind_property, bind_property_two_way


@dataclass
class _StubVM:
    """Minimal VM-shaped stub: writable property + a hub."""

    hub: MessageHub[Message]
    title: str = "initial"

    def set_title(self, value: str) -> None:
        if value == self.title:
            return
        self.title = value
        self.hub.send(PropertyChangedMessage.create(self, "stub", "title"))


def _make_vm(title: str = "initial") -> _StubVM:
    return _StubVM(hub=MessageHub[Message](), title=title)


def test_bind_property_seeds_widget_with_current_value() -> None:
    """Per docstring: widget.attr is set BEFORE the subscription."""
    vm = _make_vm(title="seed")
    widget = Static()

    sub = bind_property(widget, "renderable", vm, "title")
    try:
        assert str(widget.renderable) == "seed"
    finally:
        sub.dispose()


def test_bind_property_updates_widget_when_vm_publishes() -> None:
    vm = _make_vm(title="before")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    try:
        vm.set_title("after")
        assert str(widget.renderable) == "after"
    finally:
        sub.dispose()


def test_bind_property_ignores_messages_from_other_senders() -> None:
    vm = _make_vm(title="mine")
    other = _make_vm(title="other-initial")
    # share the hub so cross-sender leak is observable
    other.hub = vm.hub
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    try:
        other.set_title("other-changed")
        assert str(widget.renderable) == "mine"
    finally:
        sub.dispose()


def test_bind_property_ignores_other_property_names() -> None:
    vm = _make_vm(title="kept")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    try:
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "unrelated"))
        assert str(widget.renderable) == "kept"
    finally:
        sub.dispose()


def test_bind_property_dispose_stops_updates() -> None:
    vm = _make_vm(title="t0")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    sub.dispose()
    vm.set_title("t1")
    assert str(widget.renderable) == "t0"


def test_bind_property_two_way_pushes_widget_change_to_vm() -> None:
    vm = _make_vm(title="initial")
    widget = Static()
    sub = bind_property_two_way(widget, "renderable", vm, "title")
    try:
        # Simulate Textual invoking the reactive watcher.
        watcher = widget.watch_renderable  # type: ignore[attr-defined]
        watcher("initial", "via-widget")
        assert vm.title == "via-widget"
    finally:
        sub.dispose()


def test_bind_property_two_way_short_circuits_when_value_unchanged() -> None:
    """No ping-pong: the watcher must not write back values that already match."""
    vm = _make_vm(title="same")
    widget = Static()
    sub = bind_property_two_way(widget, "renderable", vm, "title")
    try:
        # If the watcher wrote back unconditionally we'd see a PropertyChangedMessage
        # on the hub even though vm.title hasn't changed. Count them:
        observed: list[object] = []
        vm.hub.messages.subscribe(on_next=observed.append)
        watcher = widget.watch_renderable  # type: ignore[attr-defined]
        watcher("same", "same")
        assert observed == []
    finally:
        sub.dispose()
