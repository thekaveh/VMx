"""Message hub — Protocol and concrete Subject-backed implementation."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from threading import Condition, RLock, get_ident
from typing import Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx
from reactivex.abc import DisposableBase, ObserverBase
from reactivex.subject import Subject

from vmx._wait_for_graph import WAITS
from vmx.messages.protocols import Message

_logger = logging.getLogger(__name__)


TMessage = TypeVar("TMessage", bound=Message, contravariant=True)


@runtime_checkable
class MessageHubProto(Protocol[TMessage]):
    """Hot pub/sub stream for IMessage events.

    Structural Protocol — any class that provides ``.messages`` and ``.send()``
    satisfies this interface without explicit inheritance.
    """

    @property
    def messages(self) -> rx.Observable[Message]:
        """Observable stream of all messages published to this hub."""
        ...

    def send(self, message: TMessage) -> None:
        """Publish *message* to all current subscribers."""
        ...


@runtime_checkable
class TransactionalMessageHubProto(MessageHubProto[TMessage], Protocol[TMessage]):
    """Additive capability for hubs that support message transactions."""

    def batch(self) -> AbstractContextManager[None]:
        """Return a synchronous, nestable message transaction scope."""
        ...


_THubMessage = TypeVar("_THubMessage", bound=Message)


class MessageHub(Generic[_THubMessage]):
    """Default Subject-backed hub.  Hot stream — no replay buffer.

    Subscriber-handler exceptions are isolated per-subscription so a raising
    handler does not terminate the stream for other subscribers (HUB-007).
    """

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()
        self._gate = Condition(RLock())
        self._pending: deque[Message] = deque()
        self._disposed: bool = False
        self._subject_termination_claimed = False
        self._drainer_thread: int | None = None
        self._batch_owner: int | None = None
        self._batch_depth = 0
        # Open borrowed scopes per borrower thread. A borrower owns the hub
        # with the batch owner and the drainer (spec/03 §4.2, ADR-0172).
        self._borrowers: dict[int, int] = {}

    def _foreign_owner_locked(self, caller: int) -> int | None:
        """Return the owner that *caller* waits for, or None when it can proceed.

        A wait names one owner: the batch owner, then the drainer, then a
        borrower other than the caller (spec/03 §4.1).
        """
        if self._batch_owner is not None and self._batch_owner != caller:
            return self._batch_owner
        if self._drainer_thread is not None and self._drainer_thread != caller:
            return self._drainer_thread
        return self._foreign_borrower_locked(caller)

    def _foreign_borrower_locked(self, caller: int) -> int | None:
        for borrower in self._borrowers:
            if borrower != caller:
                return borrower
        return None

    def _wait_for_owner_locked(self, caller: int, owner: int) -> bool:
        """Wait once for *owner*, or report that waiting would close a cycle.

        The wait records an edge to *owner* in the process-wide wait-for
        graph, so a cycle through hub, membership and ownership waits is
        visible (spec/03 §4.1, ADR-0172). The edge goes when the owner
        releases the hub, before the waiter wakes (``_wake_locked``).
        """
        if not WAITS.try_begin_owner_wait(self, caller=caller, owner=owner):
            return True
        try:
            self._gate.wait()
        finally:
            WAITS.end_wait(caller)
        return False

    def _wake_locked(self) -> None:
        """Remove edges to former owners, then wake every waiter (#1181).

        A waiter's edge stays only while the owner that it names still owns
        the hub. Once the hub is disposed, no waiter waits again.
        """
        owners: list[int] = []
        if not self._disposed:
            for owner in (self._batch_owner, self._drainer_thread):
                if owner is not None:
                    owners.append(owner)
            owners.extend(self._borrowers)
        WAITS.release_waiters(self, owners)
        self._gate.notify_all()

    @property
    def messages(self) -> rx.Observable[Message]:
        """Per HUB-007: wrap each subscription so exceptions are swallowed."""
        return rx.create(self._subscribe_safely)

    def _subscribe_safely(
        self,
        observer: ObserverBase[Message],
        scheduler: object = None,
    ) -> DisposableBase:
        def on_next(value: Message) -> None:
            try:
                observer.on_next(value)
            except Exception:
                # Isolate the failing subscriber (HUB-007): the exception is
                # swallowed so it cannot terminate the stream for other
                # subscribers (spec/03-messages.md §Subscriber resilience). It
                # is logged (not silently discarded) so the failure is still
                # observable to operators via the logging framework.
                _logger.exception(
                    "MessageHub subscriber raised while handling %r; isolating per HUB-007",
                    type(value).__name__,
                )

        return self._subject.subscribe(
            on_next=on_next,
            on_error=observer.on_error,
            on_completed=observer.on_completed,
        )

    def send(self, message: _THubMessage) -> None:
        """Publish *message* synchronously to all current subscribers."""
        caller = get_ident()
        should_drain = False
        with self._gate:
            # A borrower's own send enqueues for the drain at its borrowed
            # scope's exit (spec/03 §4.2). Any other send waits for the
            # hub's owner, and enqueues only when that wait would close a
            # cycle (spec/03 §4, HUB-013).
            if caller not in self._borrowers:
                while not self._disposed:
                    owner = self._foreign_owner_locked(caller)
                    if owner is None or self._wait_for_owner_locked(caller, owner):
                        break
            if self._disposed:
                return
            self._pending.append(message)
            if self._batch_owner is not None or self._borrowers:
                return
            if self._drainer_thread is None:
                self._drainer_thread = caller
                should_drain = True
            elif self._drainer_thread == caller:
                return

        if should_drain:
            self._drain()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Defer messages until the outermost transaction scope exits."""
        caller = get_ident()
        entered = False
        borrowed = False
        with self._gate:
            if caller in self._borrowers:
                # A borrower's nested batch nests another borrowed scope.
                borrowed = True
            else:
                while not self._disposed:
                    owner = self._foreign_owner_locked(caller)
                    if owner is None:
                        break
                    if self._wait_for_owner_locked(caller, owner):
                        borrowed = True
                        break
            if not self._disposed:
                if borrowed:
                    self._borrowers[caller] = self._borrowers.get(caller, 0) + 1
                else:
                    self._batch_owner = caller
                    self._batch_depth += 1
                entered = True
        body_error: BaseException | None = None
        try:
            yield
        except BaseException as error:
            body_error = error
        should_drain = False
        should_terminate_subject = False
        if entered:
            with self._gate:
                if borrowed:
                    depth = self._borrowers[caller] - 1
                    if depth:
                        self._borrowers[caller] = depth
                    else:
                        del self._borrowers[caller]
                    released = depth == 0
                else:
                    self._batch_depth -= 1
                    released = self._batch_depth == 0
                    if released:
                        self._batch_owner = None
                # A borrower that exits its last borrowed scope wakes the
                # waiters even while other borrowers remain (spec/03 §4.2).
                if released:
                    if (
                        not self._disposed
                        and self._pending
                        and self._drainer_thread is None
                        and self._batch_owner is None
                        and not self._borrowers
                    ):
                        self._drainer_thread = caller
                        should_drain = True
                    elif (
                        self._disposed
                        and self._drainer_thread is None
                        and self._batch_owner is None
                        and not self._borrowers
                        and not self._subject_termination_claimed
                    ):
                        self._subject_termination_claimed = True
                        should_terminate_subject = True
                    self._wake_locked()
        drain_error: BaseException | None = None
        if should_drain:
            try:
                self._drain()
            except BaseException as error:
                drain_error = error
        if should_terminate_subject:
            self._terminate_subject()
        if body_error is not None:
            raise body_error
        if drain_error is not None:
            raise drain_error

    def _drain(self) -> None:
        caller = get_ident()
        delivered = 0
        message_types: set[str] = set()
        while True:
            stop_draining = False
            should_terminate_subject = False
            message: Message | None = None
            with self._gate:
                # Wait for open borrowed scopes only while messages are
                # queued. An empty queue releases the drain, and the last
                # borrowed scope's exit drains what its body enqueued. When
                # the wait would close a cycle, the drain goes to that exit
                # with its messages still queued (spec/03 §4.2).
                release_drain = False
                while self._pending and not self._disposed:
                    borrower = self._foreign_borrower_locked(caller)
                    if borrower is None:
                        break
                    if self._wait_for_owner_locked(caller, borrower):
                        release_drain = True
                        break
                if release_drain or self._disposed or not self._pending:
                    should_terminate_subject = self._release_drainer_locked()
                    stop_draining = True
                else:
                    message = self._pending.popleft()
            if should_terminate_subject:
                self._terminate_subject()
            if stop_draining:
                return
            if __debug__:
                assert message is not None
                message_types.add(type(message).__name__)
            try:
                assert message is not None
                self._subject.on_next(message)
            except BaseException:
                try:
                    self._abandon_pending()
                except BaseException:
                    pass  # Preserve the original delivery failure.
                raise
            if __debug__:
                delivered += 1
                with self._gate:
                    has_pending = bool(self._pending)
                if delivered >= 10_000 and has_pending:
                    with self._gate:
                        message_types.update(type(item).__name__ for item in self._pending)
                    names = ", ".join(sorted(message_types))
                    cycle_error = RuntimeError(
                        "MessageHub drain exceeded 10000 messages; "
                        f"possible publish cycle involving: {names}"
                    )
                    self._abandon_pending()
                    raise cycle_error

    def _abandon_pending(self) -> None:
        should_terminate_subject = False
        with self._gate:
            self._pending.clear()
            should_terminate_subject = self._release_drainer_locked()
        if should_terminate_subject:
            self._terminate_subject()

    def _release_drainer_locked(self) -> bool:
        """Release the drainer and claim deferred subject termination.

        With a batch or borrowed scope still open, the exit of the last one
        completes the subject instead (spec/03 §4.2).
        """
        self._drainer_thread = None
        should_terminate_subject = (
            self._disposed
            and not self._subject_termination_claimed
            and self._batch_owner is None
            and not self._borrowers
        )
        if should_terminate_subject:
            self._subject_termination_claimed = True
        self._wake_locked()
        return should_terminate_subject

    def _terminate_subject(self) -> None:
        try:
            self._subject.on_completed()
        finally:
            self._subject.dispose()

    def dispose(self) -> None:
        """Complete and dispose the underlying subject."""
        caller = get_ident()
        should_terminate_subject = False
        with self._gate:
            if self._disposed:
                return
            # A borrower's own dispose, and a dispose whose wait would close a
            # cycle, record terminal intent. The owner that releases the hub
            # last completes the subject (spec/03 §4 and §4.2).
            deferred = caller in self._borrowers
            while not deferred and not self._disposed:
                owner = self._foreign_owner_locked(caller)
                if owner is None:
                    break
                deferred = self._wait_for_owner_locked(caller, owner)
            if self._disposed:
                return
            self._disposed = True
            self._pending.clear()
            if not deferred and self._drainer_thread is None:
                self._subject_termination_claimed = True
                should_terminate_subject = True
            self._wake_locked()
        if should_terminate_subject:
            self._terminate_subject()
