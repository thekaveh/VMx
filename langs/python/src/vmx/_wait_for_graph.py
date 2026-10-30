"""Internal: the process-wide wait-for graph for container membership waits.

A thread that waits for another thread's container membership transaction
records its wait before it blocks, so a wait-for cycle is visible. The wait
that would close a cycle is refused, and the caller takes its own escape
instead of waiting (ADR-0153, #1059). C# keeps the counterpart in
``VMx.Internal.WaitForGraph``, which also records hub waits. Python hub waits
keep their own graph (ADR-0166).

A wait names its resource, a container's membership gate. The owner of the
resource is looked up when a cycle is checked, so an edge stops counting as
soon as the resource is released, even before the waiter wakes (#736).
Callers may hold a container gate when they call in. The graph never takes
another lock, so its lock is always the last one taken.
"""

from __future__ import annotations

import threading


class _WaitForGraph:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owners: dict[object, int] = {}
        self._waiting_on: dict[int, object] = {}

    def acquire(self, resource: object, thread: int) -> None:
        """Record that *thread* holds *resource*."""
        with self._lock:
            self._owners[resource] = thread

    def release(self, resource: object) -> None:
        """Record that *resource* has been released."""
        with self._lock:
            self._owners.pop(resource, None)

    def try_begin_wait(self, resource: object, caller: int) -> bool:
        """Record that *caller* waits for *resource*.

        Return False, and record nothing, when that wait would close a cycle.
        """
        with self._lock:
            owner = self._owners.get(resource)
            if owner is not None and self._reaches(caller, owner):
                return False
            self._waiting_on[caller] = resource
            return True

    def end_wait(self, caller: int) -> None:
        """Remove the wait that *caller* recorded."""
        with self._lock:
            self._waiting_on.pop(caller, None)

    def is_waiting_for_testing(self, thread: int) -> bool:
        """Test-only: whether *thread* has a recorded wait."""
        with self._lock:
            return thread in self._waiting_on

    def _reaches(self, target: int, start: int) -> bool:
        # True when the chain of waits from start reaches target. Call under _lock.
        visited: set[int] = set()
        cursor: int | None = start
        while cursor is not None and cursor != target:
            if cursor in visited:
                return False
            visited.add(cursor)
            resource = self._waiting_on.get(cursor)
            cursor = None if resource is None else self._owners.get(resource)
        return cursor == target


WAITS = _WaitForGraph()
"""The shared graph that every container membership wait records in."""
