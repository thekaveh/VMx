"""The liveness helpers wait again after a timed wait returns early (#1416)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError

import pytest

import tests.liveness as liveness
from tests.liveness import future_result, join_thread, wait_event

_BOUND = 0.2
"""A short bound, so a helper that waits until its deadline ends quickly."""

_EARLY = 0.01
"""How long each early-returning wait blocks before it returns."""


class _EarlyEvent(threading.Event):
    """An event whose timed wait returns early, as after a wall-clock step."""

    def __init__(self, set_on_call: int | None = None) -> None:
        super().__init__()
        self.calls = 0
        self._set_on_call = set_on_call

    def wait(self, timeout: float | None = None) -> bool:
        self.calls += 1
        if self.calls == self._set_on_call:
            self.set()
        time.sleep(_EARLY)
        return self.is_set()


class _EarlyThread(threading.Thread):
    """A started thread whose timed join returns early, as after a wall-clock step."""

    def __init__(self) -> None:
        self.release = threading.Event()
        super().__init__(target=self.release.wait, daemon=True)
        self.calls = 0
        self.early = True

    def join(self, timeout: float | None = None) -> None:
        if not self.early:
            super().join(timeout)
            return
        self.calls += 1
        time.sleep(_EARLY)


def test_wait_event_waits_again_until_the_monotonic_deadline() -> None:
    event = _EarlyEvent()

    start = time.monotonic()
    assert wait_event(event, _BOUND) is False

    assert time.monotonic() - start >= _BOUND
    assert event.calls > 1


def test_wait_event_returns_true_once_a_later_wait_sees_the_event_set() -> None:
    event = _EarlyEvent(set_on_call=3)

    assert wait_event(event) is True

    assert event.calls == 3


def test_wait_event_returns_at_once_for_a_set_event() -> None:
    event = threading.Event()
    event.set()

    start = time.monotonic()
    assert wait_event(event) is True
    assert time.monotonic() - start < _BOUND


def test_join_thread_joins_again_until_the_monotonic_deadline() -> None:
    thread = _EarlyThread()
    thread.start()
    try:
        start = time.monotonic()
        join_thread(thread, _BOUND)

        assert time.monotonic() - start >= _BOUND
        assert thread.calls > 1
        assert thread.is_alive()
    finally:
        thread.early = False
        thread.release.set()
        join_thread(thread)


def test_join_thread_returns_once_the_thread_ends() -> None:
    release = threading.Event()
    thread = threading.Thread(target=release.wait, args=(liveness.HANG_GUARD,))
    thread.start()
    release.set()

    join_thread(thread)

    assert not thread.is_alive()


def test_join_thread_rejects_a_thread_that_never_started() -> None:
    with pytest.raises(RuntimeError):
        join_thread(threading.Thread(target=lambda: None))


def test_future_result_waits_again_until_the_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def early_wait(_futures: object, timeout: float | None = None) -> None:
        nonlocal calls
        calls += 1
        time.sleep(_EARLY)

    monkeypatch.setattr(liveness, "wait", early_wait)
    future: Future[int] = Future()

    start = time.monotonic()
    with pytest.raises(FutureTimeoutError):
        future_result(future, _BOUND)

    assert time.monotonic() - start >= _BOUND
    assert calls > 1


def test_future_result_returns_the_result_set_after_an_early_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future: Future[int] = Future()
    calls = 0

    def early_wait(_futures: object, timeout: float | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            future.set_result(7)
        time.sleep(_EARLY)

    monkeypatch.setattr(liveness, "wait", early_wait)

    assert future_result(future) == 7
    assert calls == 3
