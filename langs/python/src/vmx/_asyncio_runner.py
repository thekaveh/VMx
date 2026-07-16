"""Process-wide event-loop runner for synchronous fire-and-forget entry points."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import Future
from threading import Event, Lock, Thread
from typing import Any, TypeVar

T = TypeVar("T")


class _BackgroundEventLoop:
    def __init__(self) -> None:
        self._start_lock = Lock()
        self._ready = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None

    def submit(self, coroutine: Coroutine[Any, Any, T]) -> Future[T]:
        loop = self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coroutine, loop)

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._thread is None:
                self._thread = Thread(
                    target=self._run,
                    name="vmx-asyncio-runner",
                    daemon=True,
                )
                self._thread.start()

        self._ready.wait()
        loop = self._loop
        if loop is None:  # pragma: no cover - ready is set after assignment
            raise RuntimeError("VMx background event loop failed to start")
        return loop

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()


_BACKGROUND_EVENT_LOOP = _BackgroundEventLoop()


def submit_background(coroutine: Coroutine[Any, Any, T]) -> Future[T]:
    """Schedule *coroutine* on the shared daemon loop and return immediately."""
    return _BACKGROUND_EVENT_LOOP.submit(coroutine)
