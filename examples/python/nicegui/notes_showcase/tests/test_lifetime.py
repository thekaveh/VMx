"""Page lifetime and threading: reconnects, client deletion, worker threads, host shutdown."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from nicegui import Client, ui
from nicegui.testing.user_simulation import user_simulation
from reactivex.disposable import Disposable
from reactivex.scheduler import ThreadPoolScheduler
from vmx import ComponentVMOf, ConstructionStatus, Message, MessageHub, RxDispatcher

from nicegui_notes.adapter import bind_property, release_on_delete
from nicegui_notes.host import NotesHost


def _vm(hub: MessageHub[Message]) -> ComponentVMOf[str]:
    vm = (
        ComponentVMOf[str]
        .builder()
        .name("vm")
        .model("draft")
        .services(hub, RxDispatcher.immediate())
        .build()
    )
    vm.construct()
    return vm


def _hub_subscribers(hub: MessageHub[Message]) -> int:
    # The hub's subject is private; counting its observers is the direct way
    # to prove a binding left no subscription behind.
    return len(hub._subject.observers)


async def test_bindings_survive_a_reconnect_and_are_released_when_the_client_is_deleted() -> None:
    hub = MessageHub[Message]()
    vm = _vm(hub)
    pages: list[Client] = []

    def page() -> None:
        pages.append(ui.context.client)
        label = ui.label()
        release_on_delete(bind_property(label, "text", vm, "model"))

    async with user_simulation(page) as user:
        await user.open("/")
        client = pages[0]
        assert _hub_subscribers(hub) == 1

        # NiceGUI runs on_disconnect handlers on every disconnect, including
        # one followed by a reconnect.
        for handler in client.disconnect_handlers:
            client.safe_invoke(handler)
        vm.model = "after a reconnect"
        await user.should_see("after a reconnect")
        assert _hub_subscribers(hub) == 1

        client.delete()
        assert _hub_subscribers(hub) == 0
        vm.model = "after deletion"  # nothing is left to update

    assert vm.status is ConstructionStatus.CONSTRUCTED


async def test_a_worker_thread_change_updates_the_element_on_the_loop_inside_its_client() -> None:
    vm = _vm(MessageHub[Message]())
    seen: list[tuple[int, str]] = []
    page_state: dict[str, Any] = {}

    def record(model: str) -> str:
        seen.append((threading.get_ident(), ui.context.client.id))
        return model

    def page() -> None:
        page_state["thread"] = threading.get_ident()
        page_state["client"] = ui.context.client.id
        label = ui.label()
        release_on_delete(bind_property(label, "text", vm, "model", record))

    async with user_simulation(page) as user:
        await user.open("/")
        seen.clear()
        worker = threading.Thread(target=lambda: setattr(vm, "model", "from a worker"))
        worker.start()
        worker.join()
        await user.should_see("from a worker")

    assert seen == [(page_state["thread"], page_state["client"])]
    assert worker.ident != page_state["thread"]


async def test_the_host_builds_the_workspace_on_the_running_loop() -> None:
    host = NotesHost()
    await host.start()
    try:
        assert host.accepting
        assert host.workspace is not None and host.workspace.is_constructed
        assert host.dispatcher is not None
        assert host.dispatcher.loop is asyncio.get_running_loop()
    finally:
        await host.stop()


async def test_a_failed_start_releases_waiting_pages() -> None:
    def broken_repository() -> Any:
        raise RuntimeError("no storage")

    host = NotesHost(repository=broken_repository)
    try:
        await host.start()
    except RuntimeError:
        pass
    assert await host.ready() is False
    assert host.workspace is None


async def test_host_shutdown_releases_pages_then_the_workspace_then_the_pool() -> None:
    host = NotesHost()
    order: list[str] = []
    loop_thread = threading.get_ident()

    def page() -> None:
        host.adopt(release_on_delete(Disposable(lambda: order.append("release page bindings"))))

    async with user_simulation(page) as user:
        await host.start()
        assert host.workspace is not None and host.dispatcher is not None
        workspace = host.workspace
        pool = host.dispatcher.background
        assert isinstance(pool, ThreadPoolScheduler)
        dispose, shutdown = workspace.dispose, pool.executor.shutdown

        def recording_dispose() -> None:
            order.append("dispose workspace")
            dispose()

        def recording_shutdown(*args: Any, **kwargs: Any) -> None:
            on_loop = threading.get_ident() == loop_thread
            order.append(f"shut down pool {'on' if on_loop else 'off'} the loop thread")
            shutdown(*args, **kwargs)

        workspace.dispose = recording_dispose  # type: ignore[method-assign]
        pool.executor.shutdown = recording_shutdown  # type: ignore[method-assign]
        await user.open("/")
        await host.stop()

    assert order == [
        "release page bindings",
        "dispose workspace",
        "shut down pool off the loop thread",
    ]
    assert not host.accepting
    assert host.workspace is None
    assert workspace.status is ConstructionStatus.DISPOSED
