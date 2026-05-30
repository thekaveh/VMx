"""Unit tests for :func:`notes_showcase.views.adapter.bind_collection` (plan §4.b).

Textual's :class:`~textual.widgets.ListView` requires an active App context
before ``append`` is legal (``MountError`` otherwise), so these tests drive
the bridge through :meth:`App.run_test` / :class:`~textual.pilot.Pilot`.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, ListItem, ListView

from vmx import ComponentVM, MessageHub, RxDispatcher
from vmx.composites.composite_vm import CompositeVM
from vmx.messages.protocols import Message

from notes_showcase.views.adapter import bind_collection


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _leaf(hub: MessageHub[Message], dispatcher: RxDispatcher, name: str) -> ComponentVM:
    return ComponentVM(name=name, hint=name.upper(), hub=hub, dispatcher=dispatcher)


def _build_composite(initial: Iterable[str]) -> tuple[CompositeVM[ComponentVM], MessageHub[Message]]:
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    items = [_leaf(hub, dispatcher, n) for n in initial]
    composite: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("root")
        .hint("ROOT")
        .services(hub, dispatcher)
        .children(lambda: items)
        .build()
    )
    composite.construct()
    return composite, hub


class _Host(App[None]):
    """Minimal Textual app whose sole child is a ListView."""

    def __init__(self) -> None:
        super().__init__()
        self.list_view = ListView()

    def compose(self) -> ComposeResult:
        yield self.list_view


def _factory(vm: ComponentVM) -> ListItem:
    return ListItem(Label(vm.name))


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_bind_collection_seeds_list_view_from_vm_children() -> None:
    composite, _ = _build_composite(["a", "b", "c"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            assert len(app.list_view.children) == 3
        finally:
            sub.dispose()


@pytest.mark.asyncio
async def test_bind_collection_appends_row_on_vm_add() -> None:
    composite, hub = _build_composite(["a"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            assert len(app.list_view.children) == 1
            dispatcher = RxDispatcher.immediate()
            composite.append(_leaf(hub, dispatcher, "b"))
            await pilot.pause()
            assert len(app.list_view.children) == 2
        finally:
            sub.dispose()


@pytest.mark.asyncio
async def test_bind_collection_removes_row_on_vm_remove() -> None:
    composite, _ = _build_composite(["a", "b", "c"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            composite.remove_at(1)
            await pilot.pause()
            assert len(app.list_view.children) == 2
        finally:
            sub.dispose()


@pytest.mark.asyncio
async def test_bind_collection_rebuilds_on_reset() -> None:
    composite, _ = _build_composite(["a", "b"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            composite.clear()
            await pilot.pause()
            assert len(app.list_view.children) == 0
        finally:
            sub.dispose()


@pytest.mark.asyncio
async def test_bind_collection_mirrors_current_to_list_view_index() -> None:
    composite, _ = _build_composite(["a", "b", "c"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            composite.current = composite[2]
            await pilot.pause()
            assert app.list_view.index == 2
        finally:
            sub.dispose()


@pytest.mark.asyncio
async def test_bind_collection_pushes_widget_index_back_to_vm() -> None:
    composite, _ = _build_composite(["a", "b", "c"])
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        sub = bind_collection(app.list_view, composite, _factory)
        try:
            await pilot.pause()
            # Simulate Textual invoking the reactive watcher.
            watcher = app.list_view.watch_index  # type: ignore[attr-defined]
            watcher(None, 1)
            assert composite.current is composite[1]
        finally:
            sub.dispose()
