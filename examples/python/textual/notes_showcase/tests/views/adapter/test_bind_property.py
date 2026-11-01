"""Unit tests for :func:`notes_showcase.views.adapter.bind_property` (plan §4.b)."""

from __future__ import annotations

from dataclasses import dataclass

from textual.widgets import Static
from vmx import MessageHub
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message

from notes_showcase.views.adapter import (
    bind_property,
    bind_property_two_way,
    bind_text_area,
    push_text_area_text,
)


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
        assert str(widget.content) == "seed"
    finally:
        sub.dispose()


def test_bind_property_updates_widget_when_vm_publishes() -> None:
    vm = _make_vm(title="before")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    try:
        vm.set_title("after")
        assert str(widget.content) == "after"
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
        assert str(widget.content) == "mine"
    finally:
        sub.dispose()


def test_bind_property_ignores_other_property_names() -> None:
    vm = _make_vm(title="kept")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    try:
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "unrelated"))
        assert str(widget.content) == "kept"
    finally:
        sub.dispose()


def test_bind_property_dispose_stops_updates() -> None:
    vm = _make_vm(title="t0")
    widget = Static()
    sub = bind_property(widget, "renderable", vm, "title")
    sub.dispose()
    vm.set_title("t1")
    assert str(widget.content) == "t0"


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


class _StubTextArea:
    """TextArea-shaped stub. Like ``TextArea.text``, ``text`` is a plain
    property. Each assignment counts as one ``load_text`` call."""

    def __init__(self, text: str = "") -> None:
        self._text = text
        self.loads = 0

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        self.load_text(value)

    def load_text(self, value: str) -> None:
        self.loads += 1
        self._text = value

    def type(self, value: str) -> None:
        """Apply a typed edit without a load, as a key press does."""
        self._text += value

    def erase(self, count: int) -> None:
        """Remove the last characters without a load, as an undo does."""
        self._text = self._text[:-count]


class _RecordingVM:
    """Records each write to ``title`` and publishes it on the stub's hub."""

    def __init__(self, inner: _StubVM) -> None:
        self.hub = inner.hub
        self._inner = inner
        self.writes: list[str] = []

    @property
    def title(self) -> str:
        return self._inner.title

    @title.setter
    def title(self, value: str) -> None:
        self.writes.append(value)
        self._inner.title = value
        self.hub.send(PropertyChangedMessage.create(self, "stub", "title"))


def test_bind_text_area_seeds_and_loads_only_a_different_text() -> None:
    vm = _make_vm(title="seed")
    text_area = _StubTextArea()
    sub = bind_text_area(text_area, vm, "title")
    try:
        assert (text_area.text, text_area.loads) == ("seed", 1)
        # The same value again (for example, the echo of a typed edit) must
        # not reload the editor, because a reload moves the cursor.
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "title"))
        assert text_area.loads == 1
        vm.set_title("next")
        assert (text_area.text, text_area.loads) == ("next", 2)
    finally:
        sub.dispose()
    vm.set_title("after-dispose")
    assert text_area.text == "next"


def test_push_text_area_text_writes_only_a_different_text() -> None:
    vm = _RecordingVM(_make_vm(title="same"))
    push_text_area_text(_StubTextArea("same"), vm, "title")
    assert vm.writes == []

    push_text_area_text(_StubTextArea("typed"), vm, "title")
    assert vm.writes == ["typed"]
    assert vm.title == "typed"


def test_bind_text_area_keeps_a_typed_edit_when_an_unchanged_value_is_broadcast() -> None:
    vm = _make_vm(title="seed")
    text_area = _StubTextArea()
    sub = bind_text_area(text_area, vm, "title")
    try:
        # The key is in the editor, and its Changed message is still queued.
        text_area.type("Z")
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "title"))
        assert (text_area.text, text_area.loads) == ("seedZ", 1)
    finally:
        sub.dispose()


def test_bind_text_area_reloads_an_equal_text_when_the_identity_changes() -> None:
    vm = _make_vm(title="same")
    record = {"id": "a"}
    text_area = _StubTextArea()
    sub = bind_text_area(text_area, vm, "title", identity=lambda: record["id"])
    try:
        assert text_area.loads == 1
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "title"))
        assert text_area.loads == 1
        record["id"] = "b"
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "title"))
        assert (text_area.text, text_area.loads) == ("same", 2)
    finally:
        sub.dispose()


class _NormalizingTextArea(_StubTextArea):
    """Like ``TextArea``, rebuilds loaded text with one newline style."""

    def load_text(self, value: str) -> None:
        super().load_text(value.replace("\r\n", "\n"))


def test_bind_text_area_reloads_after_a_typed_edit_is_reverted() -> None:
    vm = _make_vm(title="seed")
    text_area = _StubTextArea()
    sub = bind_text_area(text_area, vm, "title")
    try:
        text_area.type("Z")
        vm.set_title("seedZ")  # the push of the typed edit
        vm.set_title("seed")  # a revert to the loaded value
        assert (text_area.text, text_area.loads) == ("seed", 2)
    finally:
        sub.dispose()


def test_push_text_area_text_skips_the_editor_rendition_of_a_loaded_value() -> None:
    vm = _RecordingVM(_make_vm(title="a\r\nb"))
    text_area = _NormalizingTextArea()
    sub = bind_text_area(text_area, vm, "title")
    try:
        assert text_area.text == "a\nb"
        push_text_area_text(text_area, vm, "title")
        assert vm.writes == []

        text_area.type("!")
        push_text_area_text(text_area, vm, "title")
        assert vm.writes == ["a\nb!"]

        # An undo back to the rendition restores the loaded value without a
        # reload, so the cursor stays.
        text_area.erase(1)
        push_text_area_text(text_area, vm, "title")
        assert vm.writes == ["a\nb!", "a\r\nb"]
        assert text_area.loads == 1
    finally:
        sub.dispose()


def test_push_text_area_text_keeps_a_vm_value_that_equals_the_rendition() -> None:
    inner = _make_vm(title="a\r\nb")
    vm = _RecordingVM(inner)
    text_area = _NormalizingTextArea()
    sub = bind_text_area(text_area, vm, "title")
    try:
        # Another writer sets the text that the editor already shows.
        inner.title = "a\nb"
        vm.hub.send(PropertyChangedMessage.create(vm, "stub", "title"))
        push_text_area_text(text_area, vm, "title")
        assert vm.writes == []
        assert vm.title == "a\nb"
    finally:
        sub.dispose()
