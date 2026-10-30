"""Internal: collection publication and construct walk shared by containers.

``CompositeVM`` and ``GroupVM`` keep the same collection-change delivery,
batch, auto-construct-on-add, late-child start, population-join and
construct-walk rules. Each rule has its one implementation here; the
containers' members of the same names only forward to it (spec ch. 01 §1.4,
spec/02 §6, spec/06 §5.1, spec/07).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Protocol, TypeVar

from vmx.collections._vm_collection_hub_message import collection_changed_message_for
from vmx.collections.batch import BatchUpdateHandle
from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.components._late_child_starts import _LateChildStage
from vmx.components.base import _ComponentVMBase
from vmx.lifecycle.status import ConstructionStatus

if TYPE_CHECKING:
    from reactivex.subject import Subject

    from vmx.components._late_child_starts import _LateChildStarts, _LateWalk, _StartRecord
    from vmx.messages.protocols import Message
    from vmx.services.message_hub import MessageHubProto

VM = TypeVar("VM", bound=_ComponentVMBase)


class ChildContainer(Protocol[VM]):
    """The container state the shared helpers read and update."""

    _hub: MessageHubProto[Message]
    _status: ConstructionStatus
    _auto_construct_on_add: bool
    _collection_changed_subject: Subject[CollectionChangedEvent]
    _batch_depth: int
    _batch_dirty: bool
    _population_joined: list[VM] | None
    _children: list[VM]
    _late_starts: _LateChildStarts

    @property
    def _membership_gate(self) -> AbstractContextManager[object]: ...

    def snapshot(self) -> tuple[VM, ...]: ...

    def _deliver_collection_changed(self, event: CollectionChangedEvent) -> None: ...

    def _exit_batch(self) -> None: ...

    def _maybe_auto_construct(self, child: VM) -> None: ...

    def _mark_constructed_before_publication(self) -> None: ...


def emit_collection_changed(container: ChildContainer[VM], event: CollectionChangedEvent) -> None:
    """Deliver *event* now, or mark an open batch dirty."""
    # reactivex raises on post-dispose on_next (rxjs/Combine no-op); a
    # collection mutation after dispose must be inert, not throw.
    if container._collection_changed_subject.is_disposed:
        return
    if container._batch_depth > 0:
        container._batch_dirty = True
        return
    container._deliver_collection_changed(event)


def deliver_collection_changed(
    container: ChildContainer[VM], event: CollectionChangedEvent
) -> None:
    """Deliver one committed change locally, then publish it on the hub.

    Local subscribers see the event first; exactly one
    ``CollectionChangedMessage`` sent by the container then follows on its
    hub (spec ch. 01 §1.4, ADR-0142). Every caller has already released
    the membership gate, and publication uses the hub's ordinary ``send``,
    so a hub transaction defers it. A failing local subscriber does not
    suppress the hub message for the committed change; the first failure
    is re-raised afterwards. A container disposed before or during local
    delivery publishes nothing.
    """
    subject = container._collection_changed_subject
    first_error: BaseException | None = None
    try:
        subject.on_next(event)
    except BaseException as error:
        first_error = error
    if not (subject.is_disposed or subject.is_stopped):
        try:
            container._hub.send(collection_changed_message_for(container, event))
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def enter_batch(container: ChildContainer[VM]) -> BatchUpdateHandle:
    """Open one batch level; disposing the handle closes it once."""
    container._batch_depth += 1
    return BatchUpdateHandle(container)


def exit_batch(container: ChildContainer[VM]) -> None:
    """Close one batch level; the outermost close of a dirty batch emits one reset."""
    container._batch_depth -= 1
    if (
        container._batch_depth == 0
        and container._batch_dirty
        and not container._collection_changed_subject.is_disposed
    ):
        container._batch_dirty = False
        container._deliver_collection_changed(CollectionChangedEvent(action="reset"))


def maybe_auto_construct(container: ChildContainer[VM], child: VM) -> None:
    """Construct an added *child* when auto-construct-on-add applies."""
    if not container._auto_construct_on_add:
        return
    # While Constructing, only an add with a start record starts its
    # child; any other child is in the construct walk's snapshot.
    if container._status != ConstructionStatus.CONSTRUCTED:
        return
    if child.status == ConstructionStatus.CONSTRUCTED:
        return
    child.construct()


def attach_late_start_locked(container: ChildContainer[VM], child: VM) -> _StartRecord | None:
    """Called under the gate as an add attaches *child*.

    An add that will auto-start the child while the container is
    Constructing registers a start record the construct walk waits on.
    """
    return container._late_starts.attach_locked(
        child,
        will_start=container._auto_construct_on_add
        and container._status is ConstructionStatus.CONSTRUCTING,
    )


def auto_construct_attached(
    container: ChildContainer[VM], child: VM, record: _StartRecord | None
) -> None:
    """The add's auto-construct of a child it attached with *record*."""
    if record is None:
        container._maybe_auto_construct(child)
        return
    # The construct walk never starts a late child; it waits for this
    # attempt, then joins the child (spec/06 §5.1). The record is done
    # before this add publishes or ends its transaction.
    try:
        container._late_starts.probe(child, _LateChildStage.ATTACHED)
        if child.status is ConstructionStatus.DESTRUCTED:
            child.construct()
    finally:
        record.mark_done()
        if container._status is not ConstructionStatus.CONSTRUCTING:
            container._late_starts.remove(child, record)


def join_if_pending(container: ChildContainer[VM], child: VM) -> None:
    """Record a child population left pending: the child walk joins it."""
    joined = container._population_joined
    if joined is not None and child.status not in (
        ConstructionStatus.CONSTRUCTED,
        ConstructionStatus.DISPOSED,
    ):
        joined.append(child)


def construct_walk(
    container: ChildContainer[VM],
    joined: list[VM],
    visited: dict[int, VM],
    walk: _LateWalk,
) -> Iterator[VM]:
    """Yield the construct walk's children, extended by late additions.

    The membership snapshot comes first. With auto-construct-on-add, each
    child added while the walk runs follows when its add registered a
    start record in this walk's scope: it is joined like a population
    child after that add's start attempt, so one whose own construction
    failed rolls the container back. The walk never starts a late child;
    one without a record was not started by an add, so it is skipped. The
    scope stays open after the last scan: ``_seal_or_next_late`` joins a
    child added after it, then commits Constructed under the membership
    gate and ends the scope; a failed walk ends it from ``_on_construct``
    (spec/02 §6, spec/06 §5.1).
    """
    snapshot = list(container.snapshot())
    # Keyed by id but holding each child, so a freed child's id is never
    # reused by a new member while this walk runs.
    visited.update((id(child), child) for child in snapshot)
    yield from snapshot
    if not container._auto_construct_on_add:
        walk.end()
        return
    while True:
        late = next((c for c in container.snapshot() if visited.get(id(c)) is not c), None)
        if late is None:
            return
        visited[id(late)] = late
        if walk.take(late):
            joined.append(late)
            yield late


def seal_or_next_late(
    container: ChildContainer[VM],
    joined: list[VM],
    visited: dict[int, VM],
    walk: _LateWalk,
) -> VM | None:
    """The construct walk's commit step (spec/02 §6, spec/06 §5.1).

    Under the membership gate, return the next unvisited member that an
    add started (it has a start record in this walk's scope), which the
    walk then joins. Without one, commit the Constructed state in the same
    gated section, so an add reads either Constructing (and is joined) or
    Constructed, then end the walk's scope.
    """
    with container._membership_gate:
        for child in container._children:
            if visited.get(id(child)) is child:
                continue
            visited[id(child)] = child
            if walk.take(child):
                joined.append(child)
                return child
        container._mark_constructed_before_publication()
    walk.end()
    return None
