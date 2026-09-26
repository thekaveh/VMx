"""Bounded test support for exercising the real asyncio dispatcher."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable

from reactivex.abc import DisposableBase, SchedulerBase
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
        self._admission_watchers: deque[threading.Event] = deque()
        self._admission_lock = threading.Lock()
        self._observe_foreground_admission()
        self.started = threading.Event()
        self.thread = threading.Thread(target=self._run, name="vmx-test-foreground-loop")

    def _observe_foreground_admission(self) -> None:
        """Record actual foreground schedule failures and successful enqueue."""
        foreground = self.dispatcher.foreground
        original_schedule = foreground.schedule

        def schedule(
            action: Callable[[SchedulerBase, object | None], None],
            state: object | None = None,
        ) -> DisposableBase:
            with self._admission_lock:
                watcher = self._admission_watchers.popleft() if self._admission_watchers else None
            try:
                disposable = original_schedule(action, state)
            except BaseException as error:
                self.errors.append(error)
                raise
            if watcher is not None:
                watcher.set()
            return disposable

        foreground.schedule = schedule  # type: ignore[method-assign]

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self.started.set)
        self.loop.run_forever()

    def __enter__(self) -> RunningAsyncioDispatcher:
        self.thread.start()
        if not self.started.wait(self.timeout):
            startup_error = AssertionError("foreground event loop did not start")
            self._cleanup(startup_error)
            raise startup_error
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

    def watch_next_foreground_admission(self) -> threading.Event:
        """Return an event set only after the next real loop enqueue succeeds."""
        admitted = threading.Event()
        with self._admission_lock:
            self._admission_watchers.append(admitted)
        return admitted

    def assert_event(self, event: threading.Event, description: str) -> None:
        assert event.wait(self.timeout), (
            f"timed out waiting for {description}; errors={self.errors!r}"
        )

    def _cleanup(self, original_error: BaseException | None) -> None:
        cleanup_errors: list[BaseException] = []

        def attempt(action: Callable[[], None]) -> None:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(error)

        # The pool is independent of the loop. Join it explicitly from this
        # non-pool thread while the foreground loop can still drain callbacks.
        attempt(lambda: self.background.executor.shutdown(wait=True))
        if any(worker.is_alive() for worker in self.worker_threads):
            cleanup_errors.append(AssertionError("RxPY pool workers did not stop"))
        if self.thread.is_alive():
            attempt(lambda: self.loop.call_soon_threadsafe(self.loop.stop))
            attempt(lambda: self.thread.join(self.timeout))
        if self.thread.is_alive():
            cleanup_errors.append(AssertionError("foreground event loop did not stop"))
        elif not self.loop.is_closed():
            attempt(self.loop.close)

        if original_error is not None:
            self.errors.extend(cleanup_errors)
        elif cleanup_errors:
            raise cleanup_errors[0]

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self._cleanup(exc)
