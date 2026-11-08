"""Test seams for the process-wide wait-for graph, ``vmx._wait_for_graph.WAITS``.

Hub, membership, ownership-lock, lifecycle publication and hook-lease waits
all record in ``WAITS`` (spec/03 §4.1, ADR-0172), so a test orders its threads
on recorded waits instead of on sleeps.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

import pytest

from tests.liveness import HANG_GUARD
from vmx._wait_for_graph import WAITS


def wait_until_waiting(thread: int, timeout: float = HANG_GUARD) -> None:
    """Block until *thread* has a recorded wait; raise ``TimeoutError`` otherwise."""
    deadline = time.monotonic() + timeout
    while not WAITS.is_waiting_for_testing(thread):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"thread {thread} recorded no wait")
        time.sleep(0.001)


class WaitDecisions:
    """Report hub wait decisions, and hold a woken waiter before its wait ends.

    A hub records an owner-named edge with ``WAITS.try_begin_owner_wait``.
    A waiter calls ``WAITS.end_wait`` after it wakes. Holding it there keeps it
    from removing its own edge, which is the window where a stale edge used to
    cause a false cycle escape (#1181).
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._condition = threading.Condition()
        self._decisions: dict[int, list[bool]] = defaultdict(list)
        self._holds: dict[int, tuple[int, int]] = {}
        begin_owner_wait = WAITS.try_begin_owner_wait
        end_wait = WAITS.end_wait

        def recording_begin_owner_wait(resource: object, owner: int, caller: int) -> bool:
            recorded = begin_owner_wait(resource, owner=owner, caller=caller)
            with self._condition:
                self._decisions[caller].append(recorded)
                self._condition.notify_all()
            return recorded

        def holding_end_wait(caller: int) -> None:
            with self._condition:
                hold = self._holds.pop(caller, None)
                if hold is not None:
                    decider, seen = hold
                    self._condition.wait_for(
                        lambda: len(self._decisions[decider]) > seen, HANG_GUARD
                    )
            end_wait(caller)

        monkeypatch.setattr(WAITS, "try_begin_owner_wait", recording_begin_owner_wait)
        monkeypatch.setattr(WAITS, "end_wait", holding_end_wait)

    def hold_until_decided(self, waiter: int, decider: int) -> None:
        """Hold *waiter*'s next ``end_wait`` until *decider* decides one more hub wait."""
        with self._condition:
            self._holds[waiter] = (decider, len(self._decisions[decider]))

    def decisions(self, thread: int) -> list[bool]:
        """The hub wait decisions of *thread*: True recorded a wait, False refused it."""
        with self._condition:
            return list(self._decisions[thread])
