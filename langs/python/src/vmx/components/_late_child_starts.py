"""Start records of children an auto-construct add attaches (spec/06 §5.1).

An add attaches its child under the container's membership gate and starts it
only after it releases the gate, so the container's construct walk can pull
the child first. An add that will start its child while the container is
Constructing registers a start record as it attaches the child, and marks it
done right after its construct attempt. The walk never starts a late child: it
waits for that attempt, then joins the child, so a child whose own
construction failed rolls the container back. A late child without a record
was not started by an add, so the walk skips it. Each construct walk owns a
scope of records, so a stale walk (abandoned, failed, or no longer current)
never takes or clears another walk's records, and a scope's records go with it.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from enum import Enum
from threading import Lock

from vmx.components.base import _ComponentVMBase


class _LateChildStage(Enum):
    """Test-only probe points of :class:`_LateChildStarts`."""

    ATTACHED = "attached"
    """An add attached the child with a start record and has not started it."""
    WALK_WAITING_ON_ADD = "walk_waiting_on_add"
    """The walk waits for an add to finish its start attempt."""
    WALK_ENDED = "walk_ended"
    """A construct walk ended its scope (the probe's child is the container)."""


class _StartRecord:
    """One add's start attempt of its child."""

    __slots__ = ("_attempted", "_done", "_lock", "scope")

    def __init__(self, scope: _LateWalk | None) -> None:
        self.scope = scope
        """The walk scope the record was registered in, if any."""
        self._lock = Lock()
        self._done = False
        self._attempted: Future[None] = Future()

    @property
    def attempted(self) -> Future[None]:
        """Completes once the add's construct attempt returned or raised."""
        return self._attempted

    def mark_done(self) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        # Outside the lock: a waiting walk resumes in this callback.
        self._attempted.set_result(None)


class _LateWalk:
    """One construct walk's scope of start records."""

    def __init__(self, owner: _LateChildStarts, container: object) -> None:
        self._owner = owner
        self._container = container
        self._records: dict[int, tuple[object, _StartRecord]] = {}
        # The records this walk took; only the sequential walk reads it.
        self._taken: dict[int, _StartRecord] = {}
        self._ended = False

    def _set_locked(self, child: object, record: _StartRecord | None) -> None:
        if self._ended:
            return
        if record is None:
            self._records.pop(id(child), None)
        else:
            self._records[id(child)] = (child, record)

    def _remove_locked(self, child: object, record: _StartRecord) -> None:
        entry = self._records.get(id(child))
        if entry is not None and entry[1] is record:
            del self._records[id(child)]

    def take(self, child: object) -> bool:
        """Take the record of a late child this walk visits."""
        with self._owner._lock:
            entry = self._records.get(id(child))
            if entry is None or entry[0] is not child:
                return False
            del self._records[id(child)]
        self._taken[id(child)] = entry[1]
        return True

    def end(self) -> None:
        """End this walk's scope; another walk's scope is never touched."""
        with self._owner._lock:
            if self._ended:
                return
            self._ended = True
            self._records.clear()
            if self._owner._current is self:
                self._owner._current = None
        self._owner.probe(self._container, _LateChildStage.WALK_ENDED)

    def join(self, child: object) -> Future[None] | None:
        """The walk's join of a late child, after its add's start attempt.

        Returns ``None`` for a child without a record (a population child),
        which keeps the walk's default join.
        """
        record = self._taken.get(id(child))
        if record is None:
            return None
        if record.attempted.done():
            return _join_now(child)
        self._owner.probe(child, _LateChildStage.WALK_WAITING_ON_ADD)
        joined: Future[None] = Future()

        def copy_result(settled: Future[None]) -> None:
            error = settled.exception()
            if error is None:
                joined.set_result(None)
            else:
                joined.set_exception(error)

        def join_after_attempt(_: Future[None]) -> None:
            try:
                pending = _join_now(child)
            except BaseException as error:
                joined.set_exception(error)
                return
            pending.add_done_callback(copy_result)

        record.attempted.add_done_callback(join_after_attempt)
        return joined


def _join_now(child: object) -> Future[None]:
    """Join *child* without starting it; the walk then checks its status."""
    if isinstance(child, _ComponentVMBase):
        return child._join_transition_future(construct=True)
    settled: Future[None] = Future()
    settled.set_result(None)
    return settled


class _LateChildStarts:
    """A container's start records, scoped to its current construct walk."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._current: _LateWalk | None = None
        # Test-only seam: runs at each stage. Production code never sets it.
        self.probe_for_testing: Callable[[object, _LateChildStage], None] | None = None

    def begin_walk(self, container: object) -> _LateWalk:
        """Start a construct walk's scope, before its initial snapshot."""
        walk = _LateWalk(self, container)
        with self._lock:
            self._current = walk
        return walk

    def attach_locked(self, child: object, *, will_start: bool) -> _StartRecord | None:
        """Called under the membership gate as an add attaches *child*.

        When the add will start the child (auto-construct while Constructing),
        return its record, registered in the current walk's scope if any;
        otherwise drop any earlier record of the child from that scope.
        """
        with self._lock:
            scope = self._current
            record = _StartRecord(scope) if will_start else None
            if scope is not None:
                scope._set_locked(child, record)
            return record

    def remove(self, child: object, record: _StartRecord | None) -> None:
        """Remove *record* from its scope if it is still *child*'s."""
        if record is None or record.scope is None:
            return
        with self._lock:
            record.scope._remove_locked(child, record)

    def probe(self, child: object, stage: _LateChildStage) -> None:
        probe = self.probe_for_testing
        if probe is not None:
            probe(child, stage)
