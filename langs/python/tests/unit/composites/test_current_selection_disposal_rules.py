"""Regressions for the disposed-child, Destructing and child-select rules.

ADR-0188 (#1424, #1425): a refused child ``select()`` or ``deselect()`` and a
non-null selection while the composite is Destructing change nothing and raise
nothing. ADR-0189 (#1317, #1383): walks skip a disposed child, also one that
reaches Disposed while the walk waits, and disposing the current child clears
``current``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from tests.liveness import join_thread
from vmx import ComponentVM, ForwardingComponentVM
from vmx.components.builders import ComponentVMBuilder
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _Queue:
    """A scheduler that runs nothing until the test drains it."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def drain(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


def _composite(
    hub: MessageHub[object],
    dispatcher: RxDispatcher,
    children: Iterable[ComponentVM],
    **options: Any,
) -> CompositeVM[ComponentVM]:
    items = list(children)
    builder = CompositeVMBuilder().name("p").services(hub, dispatcher).children(lambda: items)
    if options.get("async_selection"):
        builder = builder.async_selection(True)
    if "on_current_changed" in options:
        builder = builder.on_current_changed(options["on_current_changed"])
    composite: CompositeVM[ComponentVM] = builder.build()
    return composite


class _PanelVM(ComponentVM):
    """A leaf VM whose construct hook walks its members with the helper."""

    def __init__(self, hub: MessageHub[object], dispatcher: RxDispatcher, members: list[Any]):
        super().__init__(name="panel", hub=hub, dispatcher=dispatcher)
        self.members = members

    def _on_construct(self) -> None:
        self._complete_lifecycle_hook_after(self._transition_children(self.members, construct=True))


def test_helper_stops_waiting_for_a_background_member_that_is_disposed() -> None:
    fg, bg = _Queue(), _Queue()
    dispatcher = RxDispatcher(fg, bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    slow = ComponentVM(name="slow", hub=hub, dispatcher=dispatcher, background=True)
    fast = ComponentVM(name="fast", hub=hub, dispatcher=dispatcher)
    panel = _PanelVM(hub, dispatcher, [slow, fast])

    panel.construct()
    assert (panel.status, slow.status) == (S.CONSTRUCTING, S.CONSTRUCTING)

    slow.dispose()
    bg.drain()
    fg.drain()

    assert panel.status is S.CONSTRUCTED
    assert fast.status is S.CONSTRUCTED
    assert slow.status is S.DISPOSED


def test_composite_walk_stops_waiting_for_a_background_child_that_is_disposed() -> None:
    fg, bg = _Queue(), _Queue()
    dispatcher = RxDispatcher(fg, bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    slow = ComponentVM(name="slow", hub=hub, dispatcher=dispatcher, background=True)
    fast = ComponentVM(name="fast", hub=hub, dispatcher=dispatcher)
    p = _composite(hub, dispatcher, [slow, fast])

    p.construct()
    assert (p.status, slow.status) == (S.CONSTRUCTING, S.CONSTRUCTING)

    slow.dispose()
    bg.drain()
    fg.drain()

    assert p.status is S.CONSTRUCTED
    assert fast.status is S.CONSTRUCTED
    assert p.snapshot() == (slow, fast)


def test_selection_from_another_thread_during_the_destruct_walk_changes_nothing() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    errors: list[BaseException] = []

    def select_c_on_another_thread() -> None:
        def run() -> None:
            try:
                p.current = c
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        join_thread(worker, 10)
        assert not worker.is_alive()

    a = ComponentVMBuilder().name("a").services(hub, dispatcher).build()
    b = (
        ComponentVMBuilder()
        .name("b")
        .services(hub, dispatcher)
        .on_destruct(select_c_on_another_thread)
        .build()
    )
    c = ComponentVMBuilder().name("c").services(hub, dispatcher).build()
    p = _composite(hub, dispatcher, [a, b, c])
    p.construct()
    p.current = a

    p.destruct()

    assert errors == []
    assert p.status is S.DESTRUCTED
    assert p.current is None
    assert not c.is_current


def test_async_selection_delivered_while_destructing_is_dropped() -> None:
    fg = _Queue()
    dispatcher = RxDispatcher(fg, fg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    a = ComponentVMBuilder().name("a").services(hub, dispatcher).on_destruct(fg.drain).build()
    b = ComponentVMBuilder().name("b").services(hub, dispatcher).build()
    p = _composite(hub, dispatcher, [a, b], async_selection=True)
    p.construct()
    fg.drain()
    assert p.status is S.CONSTRUCTED

    p.current = b
    assert len(fg.actions) == 1
    p.destruct()
    fg.drain()

    assert p.status is S.DESTRUCTED
    assert p.current is None
    assert not b.is_current


def test_disposing_a_forwarding_current_child_clears_current() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    inner = ComponentVMBuilder().name("inner").services(hub, dispatcher).build()
    decorator: Any = ForwardingComponentVM(inner)
    other = ComponentVMBuilder().name("other").services(hub, dispatcher).build()
    changes: list[object] = []
    p = _composite(hub, dispatcher, [decorator, other], on_current_changed=changes.append)
    p.construct()
    p.current = decorator
    assert decorator.is_current
    changes.clear()

    decorator.dispose()

    assert inner.status is S.DISPOSED
    assert p.current is None
    assert not decorator.is_current
    assert changes == [None]


def test_reselecting_the_disposed_child_from_the_dispose_clear_is_refused() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    errors: list[BaseException] = []

    def on_changed(value: object) -> None:
        if value is None:
            try:
                p.current = a
            except BaseException as error:
                errors.append(error)

    a = ComponentVMBuilder().name("a").services(hub, dispatcher).build()
    b = ComponentVMBuilder().name("b").services(hub, dispatcher).build()
    p = _composite(hub, dispatcher, [a, b], on_current_changed=on_changed)
    p.construct()
    p.current = a

    a.dispose()

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "not a member" in str(errors[0])
    assert p.current is None
    assert not a.is_current


def test_disposing_a_child_that_is_not_current_publishes_nothing() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    a = ComponentVMBuilder().name("a").services(hub, dispatcher).build()
    b = ComponentVMBuilder().name("b").services(hub, dispatcher).build()
    p = _composite(hub, dispatcher, [a, b])
    p.construct()
    p.current = a
    messages: list[object] = []
    hub.messages.subscribe(
        lambda m: (
            messages.append(m) if isinstance(m, PropertyChangedMessage) and m.sender is p else None
        )
    )

    b.dispose()

    assert p.current is a
    assert messages == []


def test_dispose_clear_rechecks_the_composite_disposal_at_the_commit() -> None:
    # The composite's own dispose can start between the dispose clear's first
    # check and its commit. The commit checks again and clears nothing, so the
    # composite's dispose cascade publishes no Current change (ADR-0189 rule 6).
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    a = ComponentVMBuilder().name("a").services(hub, dispatcher).build()
    changes: list[object] = []
    p = _composite(hub, dispatcher, [a], on_current_changed=changes.append)
    p.construct()
    p.current = a
    changes.clear()
    apply_current_change = p._apply_current_change

    def dispose_starts_first(*args: Any, **kwargs: Any) -> None:
        p._dispose_requested = True
        apply_current_change(*args, **kwargs)

    p._apply_current_change = dispose_starts_first  # type: ignore[method-assign]

    a.dispose()

    assert p.current is a
    assert changes == []
