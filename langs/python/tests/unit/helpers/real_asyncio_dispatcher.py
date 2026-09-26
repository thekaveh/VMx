"""Bounded test support for exercising the real asyncio dispatcher."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from reactivex.scheduler import ThreadPoolScheduler

from vmx.services.dispatcher import RxDispatcher


class RunningAsyncioDispatcher:
    """Own a debug asyncio loop thread and its independent RxPY worker pool."""

    timeout = 5.0

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.loop.set_debug(True)
        self.dispatcher = RxDispatcher.asyncio(self.loop)
        assert isinstance(self.dispatcher.background, ThreadPoolScheduler)
        self.background = self.dispatcher.background
        self.worker_threads: list[threading.Thread] = []
        self.errors: list[BaseException] = []
        self.started = threading.Event()
        self.thread = threading.Thread(target=self._run, name="vmx-test-foreground-loop")

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self.started.set)
        self.loop.run_forever()

    def __enter__(self) -> RunningAsyncioDispatcher:
        self.thread.start()
        assert self.started.wait(self.timeout), "foreground event loop did not start"
        return self

    def record_worker(self) -> None:
        self.worker_threads.append(threading.current_thread())

    def schedule_background(self, action: Callable[[], None]) -> threading.Event:
        """Submit an action and capture worker failures for useful assertions."""
        finished = threading.Event()

        def run(_scheduler: object, _state: object = None) -> None:
            self.record_worker()
            try:
                action()
            except BaseException as error:
                self.errors.append(error)
            finally:
                finished.set()

        self.background.schedule(run)
        return finished

    def assert_event(self, event: threading.Event, description: str) -> None:
        assert event.wait(self.timeout), (
            f"timed out waiting for {description}; errors={self.errors!r}"
        )

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        # The pool is independent of the loop. Join it explicitly from this
        # non-pool thread while the foreground loop can still drain callbacks.
        self.background.executor.shutdown(wait=True)
        assert all(not worker.is_alive() for worker in self.worker_threads)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(self.timeout)
        assert not self.thread.is_alive(), "foreground event loop did not stop"
        self.loop.close()
