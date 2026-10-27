"""Internal: collection publication and construct walk shared by containers.

``CompositeVM`` and ``GroupVM`` keep the same collection-change delivery,
auto-construct-on-add, population-join and construct-walk rules. Each rule has
its one implementation here; the containers' members of the same names only
forward to it (spec ch. 01 §1.4, spec/02 §6, spec/06 §5.1, spec/07).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol, TypeVar

from vmx.collections._vm_collection_hub_message import collection_changed_message_for
from vmx.components.base import _ComponentVMBase
from vmx.lifecycle.status import ConstructionStatus

if TYPE_CHECKING:
    from reactivex.subject import Subject

    from vmx.collections.collection_changed import CollectionChangedEvent
    from vmx.components._late_child_starts import _LateWalk
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

    def snapshot(self) -> tuple[VM, ...]: ...

    def _deliver_collection_changed(self, event: CollectionChangedEvent) -> None: ...


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
