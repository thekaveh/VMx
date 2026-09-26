"""Real-loop tests for the Textual VMx dispatcher bridge."""

from __future__ import annotations

import asyncio
import threading

import pytest
from reactivex.scheduler import ThreadPoolScheduler
from textual.app import App
from vmx.components.component_vm import ComponentVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.message_hub import MessageHub

from notes_showcase.views.adapter.dispatcher import TextualDispatcher


def test_dispatcher_rejects_app_before_mount() -> None:
    with pytest.raises(RuntimeError, match="running App event loop"):
        TextualDispatcher(App())


@pytest.mark.asyncio
async def test_background_lifecycle_completion_returns_to_textual_app_loop() -> None:
    app: App[object] = App()
    async with app.run_test():
        loop = asyncio.get_running_loop()
        original_debug = loop.get_debug()
        loop.set_debug(True)
        try:
            dispatcher = TextualDispatcher(app)
            assert isinstance(dispatcher.background, ThreadPoolScheduler)
            hub: MessageHub[object] = MessageHub()
            hook_threads: list[int] = []
            terminal_threads: list[int] = []
            terminal = asyncio.Event()

            def hook() -> None:
                hook_threads.append(threading.get_ident())

            vm = (
                ComponentVM.builder()
                .name("textual-real-loop")
                .services(hub, dispatcher)
                .background(True)
                .on_construct(hook)
                .build()
            )
            subscription = hub.messages.subscribe(
                lambda message: (
                    (terminal_threads.append(threading.get_ident()), terminal.set())
                    if isinstance(message, ConstructionStatusChangedMessage)
                    and message.sender is vm
                    and message.status is ConstructionStatus.CONSTRUCTED
                    else None
                )
            )
            try:
                vm.construct()
                await asyncio.wait_for(terminal.wait(), timeout=5)
                assert terminal_threads == [threading.get_ident()]
                assert len(hook_threads) == 1
                assert hook_threads[0] != threading.get_ident()
            finally:
                subscription.dispose()
                vm.dispose()
                await asyncio.to_thread(dispatcher.background.executor.shutdown, wait=True)
        finally:
            loop.set_debug(original_debug)
