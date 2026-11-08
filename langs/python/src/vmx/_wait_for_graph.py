"""Internal: the process-wide wait-for graph for blocking waits between VMx resources.

A thread that waits for a resource that another thread owns records its wait
before it blocks, so a wait-for cycle is visible. The wait that would close a
cycle is refused, and the caller takes its own escape, or raises its own error,
instead of waiting (spec/03 §4.1, ADR-0172). These waits record here:
container membership transactions (ADR-0153, #1059), child ownership locks
(#1155) and message hub batch, drain and borrowed-scope waits (#1157, #1179).
The lifecycle publication and hook-lease waits in ``vmx.components.base``
still use their own graph; ADR-0172 moves them here too (#1182). C# keeps the
counterpart in ``VMx.Internal.WaitForGraph``.

An edge names the waiting thread and one resource instance: a container's
membership gate, a child's ownership lock or a hub. It finds the resource's
owner in one of two ways.

- **Resource-named edge** (:meth:`_WaitForGraph.try_begin_wait`). The owner
  is looked up in the recorded holders when a cycle is checked. The holder
  calls :meth:`_WaitForGraph.release` before it releases the resource, so the
  edge stops counting at once, even before the waiter wakes (#736). Membership
  gates and ownership locks use this form.
- **Owner-named edge** (:meth:`_WaitForGraph.try_begin_owner_wait`). The edge
  names the owner thread when the wait starts. A hub has several owners (the
  batch owner, the drainer and any borrowers), so it names the one that the
  caller waits for. Before the hub wakes its waiters, the releasing thread
  calls :meth:`_WaitForGraph.release_waiters` with the hub's remaining owners.
  That removes every edge that names a former owner (#1181).

A waiting thread has at most one edge, because it blocks in one wait at a
time. Callers may hold a container gate, an ownership lock or a hub gate when
they call in. The graph never takes another lock and runs no consumer code, so
its lock is always the last one taken.
"""

from __future__ import annotations

import threading
from collections.abc import Collection


class _WaitForGraph:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owners: dict[object, int] = {}
        # waiter thread -> (resource, named owner or None for a resource-named edge)
        self._waiting_on: dict[int, tuple[object, int | None]] = {}

    def acquire(self, resource: object, thread: int) -> None:
        """Record that *thread* holds *resource*."""
        with self._lock:
            self._owners[resource] = thread

    def release(self, resource: object) -> None:
        """Record that *resource* has been released."""
        with self._lock:
            self._owners.pop(resource, None)

    def try_begin_wait(self, resource: object, caller: int) -> bool:
        """Record that *caller* waits for *resource*, whose holder is recorded.

        Return False, and record nothing, when that wait would close a cycle.
        """
        with self._lock:
            owner = self._owners.get(resource)
            if owner is not None and self._reaches(caller, owner):
                return False
            self._waiting_on[caller] = (resource, None)
            return True

    def try_begin_owner_wait(self, resource: object, owner: int, caller: int) -> bool:
        """Record that *caller* waits for *owner* to release *resource*.

        Return False, and record nothing, when that wait would close a cycle.
        """
        with self._lock:
            if self._reaches(caller, owner):
                return False
            self._waiting_on[caller] = (resource, owner)
            return True

    def end_wait(self, caller: int) -> None:
        """Remove the wait that *caller* recorded."""
        with self._lock:
            self._waiting_on.pop(caller, None)

    def release_waiters(self, resource: object, current_owners: Collection[int]) -> None:
        """Remove owner-named edges on *resource* whose owner is not current.

        The thread that releases its part of *resource* calls this before it
        wakes the waiters. A woken waiter that must still wait records its
        wait again.
        """
        with self._lock:
            stale = [
                waiter
                for waiter, (waited, owner) in self._waiting_on.items()
                if waited is resource and owner is not None and owner not in current_owners
            ]
            for waiter in stale:
                del self._waiting_on[waiter]

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
            edge = self._waiting_on.get(cursor)
            if edge is None:
                return False
            resource, named_owner = edge
            cursor = named_owner if named_owner is not None else self._owners.get(resource)
        return cursor == target


WAITS = _WaitForGraph()
"""The shared graph that every blocking wait between VMx resources records in."""
