"""Liveness bound and monotonic-deadline waits for tests that wait on another thread."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, wait
from typing import TypeVar

_T = TypeVar("_T")

HANG_GUARD: float = 30.0
"""The bound, in seconds, for a wait that is expected to succeed (#546, #1074).

A slow or oversubscribed runner can delay a thread by seconds, so short
deadlines fail without any wrong behavior. A passing wait returns as soon as
its condition holds, so the bound costs nothing; it only stops a hang.

Use it for positive waits, the waits whose success the test expects. Make a
positive ``Event.wait``, ``Thread.join`` or ``Future.result`` through
``wait_event``, ``join_thread`` or ``future_result`` (#1416). On macOS,
CPython times one lock wait against the wall clock, so a clock step on a CI
runner can end a plain timed wait early. Each helper checks a
``time.monotonic`` deadline and waits again until that deadline passes.
``Barrier.wait`` and ``Condition.wait_for`` already wait again until a
monotonic deadline passes, so they take ``HANG_GUARD`` directly, as does
``asyncio.wait_for``.

An outer wait that must outlive inner ``HANG_GUARD`` waits, such as a join on
a thread that waits itself, uses a multiple of the bound, so the inner failure
is the one reported. A blocking hold that a main-thread positive wait must
time out before also uses a multiple, so a regression cannot pass because the
hold expired first.

A negative window asserts that something did *not* happen, such as
``assert not done.wait(0.05)``. It keeps its short plain wait, because its
full duration elapses on every passing run and an early return cannot make
it fail.
"""


def wait_event(event: threading.Event, bound: float = HANG_GUARD) -> bool:
    """Return whether ``event`` is set within ``bound`` seconds of monotonic time.

    ``Event.wait(timeout)`` makes one timed lock wait. This helper waits again
    after an early return until the monotonic deadline passes.
    """
    deadline = time.monotonic() + bound
    while True:
        if event.wait(max(0.0, deadline - time.monotonic())):
            return True
        if time.monotonic() >= deadline:
            return event.is_set()


def join_thread(thread: threading.Thread, bound: float = HANG_GUARD) -> None:
    """Join ``thread`` for up to ``bound`` seconds of monotonic time.

    Like ``Thread.join(timeout)``, the helper returns ``None``; the caller
    checks ``thread.is_alive()`` when the outcome matters. ``Thread.join``
    makes one timed lock wait, so this helper joins again after an early
    return until the monotonic deadline passes.
    """
    deadline = time.monotonic() + bound
    while True:
        thread.join(max(0.0, deadline - time.monotonic()))
        if not thread.is_alive() or time.monotonic() >= deadline:
            return


def future_result(future: Future[_T], bound: float = HANG_GUARD) -> _T:
    """Return ``future.result()`` once the future finishes within ``bound`` seconds.

    ``Future.result(timeout)`` can return early on macOS. There, CPython times
    the wait against the wall clock, and a clock step on a CI runner ends the
    wait before the future finishes. This helper checks a monotonic
    deadline and waits again until that deadline passes. A future that is
    still pending at the deadline raises ``TimeoutError``.
    """
    deadline = time.monotonic() + bound
    while not future.done():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        wait([future], timeout=remaining)
    return future.result(timeout=0)
