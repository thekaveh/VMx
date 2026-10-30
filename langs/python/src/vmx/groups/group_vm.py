"""GroupVM — ordered peer-child container with no selection slot.

GroupVM<VM> is a container of peers: an ordered list of child VMs with no
``current`` selection and no child-navigation commands. It is identical to
CompositeVM minus the Current slot and minus selection-related members.

Children ARE constructed/destructed in concert (parallel within synchronous
execution), matching CompositeVM's orchestration contract.

See spec/07-group-vm.md.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Iterator
from threading import Condition, RLock, get_ident
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import DisposableBase
from reactivex.subject import Subject

from vmx._disposal import _run_disposal_steps as _run_every_step
from vmx._indexes import _reject_bool_index
from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.components._container_helpers import (
    attach_late_start_locked,
    auto_construct_attached,
    construct_walk,
    deliver_collection_changed,
    emit_collection_changed,
    enter_batch,
    exit_batch,
    join_if_pending,
    maybe_auto_construct,
    seal_or_next_late,
)
from vmx.components._late_child_starts import (
    _LateChildStarts,
    _LateWalk,
    _StartRecord,
)
from vmx.components.base import (
    _begin_parent_transfer,
    _commit_parent_transfer,
    _ComponentVMBase,
    _ownership_reservation_batch,
    _ParentCompositeVM,
    _ParentTransfer,
)
from vmx.components.child_order import ChildOrder, _in_destruct_order
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHubProto

VM = TypeVar("VM", bound=_ComponentVMBase)


# ---------------------------------------------------------------------------
# GroupVM[VM]
# ---------------------------------------------------------------------------


class GroupVM(Generic[VM], _ComponentVMBase):
    """Ordered peer-child container viewmodel.

    Children are added via the builder's ``children`` factory (evaluated lazily
    on the first ``construct()``) or by calling ``add()`` / ``insert()``
    manually before construction.

    Key differences from CompositeVM:
    - No ``current`` property.
    - No ``select_next_command`` / ``select_previous_command`` for navigating
      children (children are peers — these commands are always-False no-ops
      inherited from the ComponentVMProto baseline in ``_ComponentVMBase``).
    - No ``select_component`` / ``deselect_component`` / ``can_select_component``.
    - ``select_command`` / ``deselect_command`` ARE present (operate on the
      group's own selection within its parent).

    Implements ``MutableSequence``-like interface: ``__getitem__``, ``__setitem__``,
    ``__delitem__``, ``__len__``, ``__iter__``, ``__contains__``, ``insert``,
    ``append`` / ``add``, ``remove``, ``remove_at`` / ``__delitem__``, ``clear``.

    Observable ``on_collection_changed`` emits :class:`CollectionChangedEvent`
    on every structural change.

    Type identifier: ``ViewModelType.GROUP``.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str = "",
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        auto_construct_on_add: bool = False,
        children_factory: Callable[[], Iterable[VM]] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=on_construct,
            on_destruct=on_destruct,
        )
        self._auto_construct_on_add: bool = auto_construct_on_add
        # Fixed at build time: the destruct walk and dispose cascade order (ADR-0161).
        self._destruct_order: ChildOrder = destruct_order
        self._children: list[VM] = []
        self._children_factory: Callable[[], Iterable[VM]] | None = children_factory
        self._populated: bool = False
        # Collects the children population started constructing (see _on_construct).
        self._population_joined: list[VM] | None = None
        self._batch_depth: int = 0
        self._batch_dirty: bool = False
        self._dispose_requested: bool = False
        self._dispose_deferred: bool = False
        self._membership_transaction_active: bool = False
        self._membership_transaction_owner: int | None = None
        self._membership_gate = RLock()
        # Start records of the children an auto-construct add attaches while
        # Constructing; the construct walk waits on them (spec/06 §5.1).
        self._late_starts = _LateChildStarts()
        self._membership_condition = Condition(self._membership_gate)

        # Observable collection-change stream.
        self._collection_changed_subject: Subject[CollectionChangedEvent] = Subject()

        # Single cached parent adaptor reused for every child op (VMX-077):
        # a fresh _GroupParent per add/insert was wasteful and gave children an
        # unstable parent identity. Lazily created on first use.
        self._group_parent: _GroupParent[VM] | None = None

    # ── ViewModelType ────────────────────────────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.GROUP

    # ── Collection-change observable ─────────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedEvent]:
        """Observable that emits :class:`CollectionChangedEvent` on structural changes.

        The backing Subject is sealed behind ``as_observable`` so external
        callers can only subscribe — never ``on_next``/``dispose`` the internal
        stream (VMX-013). The public type is ``Observable`` (was ``Subject``).
        """
        return self._collection_changed_subject.pipe(ops.as_observable())

    def snapshot(self) -> tuple[VM, ...]:
        """Return the current ordered child-membership snapshot."""
        with self._membership_gate:
            return tuple(self._children)

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase:
        """Subscribe to payload-free structural child-membership pulses."""
        return self.on_collection_changed.subscribe(lambda _event: callback())

    # ── MutableSequence-like interface ───────────────────────────────────────

    def __len__(self) -> int:
        with self._membership_gate:
            return len(self._children)

    def __iter__(self) -> Iterator[VM]:
        return iter(self.snapshot())

    def __contains__(self, item: object) -> bool:
        with self._membership_gate:
            return any(child is item for child in self._children)

    def __getitem__(self, index: int) -> VM:
        with self._membership_gate:
            return self._children[index]

    def __setitem__(self, index: int, value: VM) -> None:
        _reject_bool_index(index)
        # Emit the actual position; a negative index counts from the end
        # (mirrors insert/remove_at and ObservableList).
        parent = self._as_parent()
        if value is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        old: VM | None = None
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        try:
            original_status = value.status
            transfer = _begin_parent_transfer(value, parent)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                resolved_index = index + len(self._children) if index < 0 else index
                old = self._children[index]
                self._children[index] = value
                old._set_parent(None)
                value._set_parent(parent)
                record = self._attach_late_start_locked(value)
            self._auto_construct_attached(value, record)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            with self._membership_gate:
                if old is not None and any(child is value for child in self._children):
                    actual_index = next(
                        i for i, child in enumerate(self._children) if child is value
                    )
                    self._children[actual_index] = old
                    old._set_parent(parent)
                    value._set_parent(None)
                self._late_starts.remove(value, record)
            if (
                original_status is ConstructionStatus.DESTRUCTED
                and value.status is ConstructionStatus.CONSTRUCTED
            ):
                try:
                    value.destruct()
                except BaseException as error:
                    compensation_error = error
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)

            def raise_commit_error() -> None:
                if commit_error is not None:
                    raise commit_error

            # The change is committed: every publication step runs even when an
            # earlier one raises, and the first failure is re-raised (#727).
            _run_every_step(
                raise_commit_error,
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(
                        action="remove", old_items=(old,), old_index=resolved_index
                    )
                ),
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(
                        action="add", new_items=(value,), new_index=resolved_index
                    )
                ),
            )
        finally:
            self._end_membership_transaction(propagate_dispose_failure=sys.exc_info()[0] is None)

    def __delitem__(self, index: int) -> None:
        self.remove_at(index)

    def index_of(self, item: VM) -> int:
        """Return the index of *item*, or ``-1`` if not found."""
        return next(
            (index for index, child in enumerate(self.snapshot()) if child is item),
            -1,
        )

    def insert(self, index: int, item: VM) -> None:
        """Insert *item* at *index*, shifting existing children right.

        The emitted ``new_index`` is the actual insertion position (stdlib
        semantics: negatives count from the end, out-of-range clamps).
        """
        _reject_bool_index(index)
        parent = self._as_parent()
        if item is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        try:
            original_status = item.status
            transfer = _begin_parent_transfer(item, parent)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                if index < 0:
                    index = max(index + len(self._children), 0)
                elif index > len(self._children):
                    index = len(self._children)
                self._children.insert(index, item)
                item._set_parent(parent)
                attached = True
                record = self._attach_late_start_locked(item)
            self._auto_construct_attached(item, record)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            with self._membership_gate:
                if attached and any(child is item for child in self._children):
                    self._children.remove(item)
                    item._set_parent(None)
                self._late_starts.remove(item, record)
            if (
                original_status is ConstructionStatus.DESTRUCTED
                and item.status is ConstructionStatus.CONSTRUCTED
            ):
                try:
                    item.destruct()
                except BaseException as error:
                    compensation_error = error
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)
            self._emit_collection_changed(
                CollectionChangedEvent(action="add", new_items=(item,), new_index=index)
            )
            if commit_error is not None:
                raise commit_error
        finally:
            self._end_membership_transaction(propagate_dispose_failure=sys.exc_info()[0] is None)

    def add(self, item: VM) -> None:
        """Append *item* to the end of the children list."""
        parent = self._as_parent()
        if item is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        try:
            original_status = item.status
            transfer = _begin_parent_transfer(item, parent)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                idx = len(self._children)
                self._children.append(item)
                item._set_parent(parent)
                attached = True
                record = self._attach_late_start_locked(item)
            self._auto_construct_attached(item, record)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            with self._membership_gate:
                if attached and any(child is item for child in self._children):
                    self._children.remove(item)
                    item._set_parent(None)
                self._late_starts.remove(item, record)
            if (
                original_status is ConstructionStatus.DESTRUCTED
                and item.status is ConstructionStatus.CONSTRUCTED
            ):
                try:
                    item.destruct()
                except BaseException as error:
                    compensation_error = error
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)
            self._emit_collection_changed(
                CollectionChangedEvent(action="add", new_items=(item,), new_index=idx)
            )
            if commit_error is not None:
                raise commit_error
        finally:
            self._end_membership_transaction(propagate_dispose_failure=sys.exc_info()[0] is None)

    # Alias: append mirrors Python list convention.
    append = add

    def remove(self, item: VM) -> bool:
        """Remove first occurrence of *item*. Returns True if removed."""
        with self._membership_gate:
            self._require_child_admission()
            idx = next((i for i, child in enumerate(self._children) if child is item), -1)
            if idx < 0:
                return False
            removed = self._remove_at_locked(idx)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(removed,), old_index=idx)
        )
        return True

    def remove_at(self, index: int) -> None:
        """Remove the child at *index*.

        The emitted ``old_index`` is the actual removal position; a negative
        index counts from the end (mirrors :meth:`insert` and
        ``ObservableList.remove_at``).
        """
        _reject_bool_index(index)
        with self._membership_gate:
            resolved_index = index + len(self._children) if index < 0 else index
            self._require_child_admission()
            item = self._remove_at_locked(index)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(item,), old_index=resolved_index)
        )

    def clear(self) -> None:
        """Remove all children."""
        with self._membership_gate:
            self._require_child_admission()
            for child in self._children:
                if child._parent is self._as_parent():
                    child._set_parent(None)
            self._children.clear()
        self._emit_collection_changed(CollectionChangedEvent(action="reset"))

    def move(self, from_index: int, to_index: int) -> None:
        """Move an existing peer to its final index without rewiring it."""
        with self._membership_gate:
            self._require_child_admission()
            self._validate_move_index(from_index)
            self._validate_move_index(to_index)
            if from_index == to_index:
                return
            item = self._children.pop(from_index)
            self._children.insert(to_index, item)
        self._emit_collection_changed(
            CollectionChangedEvent(
                action="move",
                new_items=(item,),
                new_index=to_index,
                old_items=(item,),
                old_index=from_index,
            )
        )

    def _remove_at_locked(self, index: int) -> VM:
        item = self._children[index]
        del self._children[index]
        if item._parent is self._as_parent():
            item._set_parent(None)
        return item

    # ── Batch + auto-construct (spec v1.1) ──────────────────────────────────

    def batch_update(self) -> BatchUpdateHandle:
        """Open a ref-counted batch suppressing per-mutation events.

        Returns a context manager / disposable. When the outermost handle is
        disposed, a single ``CollectionChangedEvent(action='reset')`` is emitted
        iff at least one mutation occurred while any batch was open.
        """
        return enter_batch(self)

    def _exit_batch(self) -> None:
        exit_batch(self)

    def _emit_collection_changed(self, event: CollectionChangedEvent) -> None:
        emit_collection_changed(self, event)

    def _deliver_collection_changed(self, event: CollectionChangedEvent) -> None:
        deliver_collection_changed(self, event)

    def _attach_late_start_locked(self, child: VM) -> _StartRecord | None:
        return attach_late_start_locked(self, child)

    def _auto_construct_attached(self, child: VM, record: _StartRecord | None) -> None:
        auto_construct_attached(self, child, record)

    def _maybe_auto_construct(self, child: VM) -> None:
        maybe_auto_construct(self, child)

    def _construct_walk(
        self, joined: list[VM], visited: dict[int, VM], walk: _LateWalk
    ) -> Iterator[VM]:
        return construct_walk(self, joined, visited, walk)

    def _seal_or_next_late(
        self, joined: list[VM], visited: dict[int, VM], walk: _LateWalk
    ) -> VM | None:
        return seal_or_next_late(self, joined, visited, walk)

    def _validate_move_index(self, index: int) -> None:
        _reject_bool_index(index)
        if index < 0 or index >= len(self._children):
            raise IndexError(f"move index {index} out of range for {len(self._children)} children")

    # ── Lifecycle overrides ──────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate from factory (once) then construct every child."""
        # Invoke the builder's on_construct callback first.
        if self._on_construct_cb is not None:
            self._on_construct_cb()
        # Children whose construct population started are joined, not restarted.
        joined: list[VM] = []
        self._population_joined = joined
        try:
            self._populate_children()
        finally:
            self._population_joined = None
        # This walk's scope of start records, begun before its snapshot.
        walk = self._late_starts.begin_walk(self)
        visited: dict[int, VM] = {}
        walking = self._transition_container_children(
            self._construct_walk(joined, visited, walk),
            construct=True,
            joined=joined,
            join=walk.join,
            seal=(
                (lambda: self._seal_or_next_late(joined, visited, walk))
                if self._auto_construct_on_add
                else None
            ),
        )

        # A failed walk ends its own scope when it fails, not at a later GC.
        walking.add_done_callback(lambda _: walk.end())
        self._complete_lifecycle_hook_after(walking)

    def _on_destruct(self) -> None:
        """Destruct every child in the destruct order, then invoke the on_destruct callback."""
        self._complete_lifecycle_hook_after(
            self._transition_children(
                _in_destruct_order(self.snapshot(), self._destruct_order),
                construct=False,
                after=self._on_destruct_cb,
            )
        )

    def dispose(self) -> None:
        """Dispose cascade (LIFE-013): depth-first dispose each child, then self."""
        with self._membership_condition:
            if self._dispose_requested:
                return
            while (
                self._membership_transaction_active
                and self._membership_transaction_owner != get_ident()
            ):
                self._membership_condition.wait()
                if self._dispose_requested:
                    return
            if self._membership_transaction_active:
                self._dispose_deferred = True
                return
            self._dispose_requested = True
            snapshot = _in_destruct_order(self._children, self._destruct_order)
        # The cascade runs at the base's admitted-hook boundary (LIFE-015): a
        # foreign dispose cleans no child while this container's hook runs. No
        # lock is held here, so the hook can finish while this call waits.
        self._dispose_with_children(snapshot)

    def _require_child_admission(self) -> None:
        if self._dispose_requested or self._dispose_deferred:
            raise RuntimeError("cannot attach a child while the container is disposing")
        if self._membership_transaction_active:
            raise RuntimeError("container membership transaction is already in progress")

    def _begin_membership_transaction_locked(self) -> None:
        self._require_child_admission()
        self._membership_transaction_active = True
        self._membership_transaction_owner = get_ident()

    def _require_transaction_can_continue_locked(self) -> None:
        if self._dispose_requested or self._dispose_deferred:
            raise RuntimeError("cannot attach a child while the container is disposing")

    def _begin_membership_transaction(self) -> None:
        with self._membership_gate:
            self._begin_membership_transaction_locked()

    def _end_membership_transaction(self, *, propagate_dispose_failure: bool = True) -> None:
        with self._membership_condition:
            self._membership_transaction_active = False
            self._membership_transaction_owner = None
            dispose = self._dispose_deferred
            self._dispose_deferred = False
            self._membership_condition.notify_all()
        if dispose:
            try:
                self.dispose()
            except BaseException:
                if propagate_dispose_failure:
                    raise

    def _on_dispose(self) -> None:
        if not self._collection_changed_subject.is_disposed:
            self._collection_changed_subject.on_completed()
            self._collection_changed_subject.dispose()

    def _join_if_pending(self, child: VM) -> None:
        join_if_pending(self, child)

    def _populate_children(self) -> None:
        """Evaluate the children factory (idempotent: runs at most once)."""
        if self._populated or self._children_factory is None:
            return
        children = list(self._children_factory())
        if len({id(child._ownership_identity) for child in children}) != len(children):
            raise ValueError(
                "factory population contains a duplicate child identity "
                "(duplicate canonical child identity)"
            )
        parent = self._as_parent()
        self._begin_membership_transaction()
        transfers: list[_ParentTransfer | None] = []
        original_statuses: list[ConstructionStatus] = []
        try:
            with _ownership_reservation_batch(children):
                for child in children:
                    transfer = _begin_parent_transfer(child, parent)
                    transfers.append(transfer)
                    original_statuses.append(child.status)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                for child in children:
                    self._children.append(child)
                    child._set_parent(parent)

            # Make the entire factory snapshot visible before any child hook,
            # but do not run user lifecycle code while holding the gate.
            for child in children:
                if (
                    self.status is ConstructionStatus.CONSTRUCTING
                    and child.status is not ConstructionStatus.CONSTRUCTED
                ):
                    child.construct()
                    # A child population left pending is joined, never restarted.
                    self._join_if_pending(child)
                else:
                    self._maybe_auto_construct(child)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            for child, original_status in reversed(
                list(zip(children, original_statuses, strict=False))
            ):
                with self._membership_gate:
                    if any(candidate is child for candidate in self._children):
                        self._children.remove(child)
                if (
                    original_status is ConstructionStatus.DESTRUCTED
                    and child.status is ConstructionStatus.CONSTRUCTED
                ):
                    try:
                        child.destruct()
                    except BaseException as error:
                        if compensation_error is None:
                            compensation_error = error
                if child._parent is parent:
                    child._set_parent(None)
            for staged_transfer in reversed(transfers):
                if staged_transfer is not None:
                    staged_transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error: BaseException | None = None
            for staged_transfer in transfers:
                commit_failure = _commit_parent_transfer(staged_transfer)
                if commit_error is None:
                    commit_error = commit_failure
            self._populated = True
            population_error = commit_error

            def raise_commit_error() -> None:
                if population_error is not None:
                    raise population_error

            def publish_add(child: VM) -> None:
                index = next(i for i, candidate in enumerate(self.snapshot()) if candidate is child)
                self._emit_collection_changed(
                    CollectionChangedEvent(action="add", new_items=(child,), new_index=index)
                )

            # Every committed child publishes, even after a raising subscriber;
            # the first failure is re-raised (#727).
            _run_every_step(
                raise_commit_error,
                *(lambda child=child: publish_add(child) for child in children),
            )
        finally:
            self._end_membership_transaction(propagate_dispose_failure=sys.exc_info()[0] is None)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _as_parent(self) -> _GroupParent[VM]:
        """Return the cached _ParentCompositeVM adaptor for child.set_parent() calls."""
        if self._group_parent is None:
            self._group_parent = _GroupParent(self)
        return self._group_parent

    # ── count property alias ─────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of children (alias for ``len(group)``)."""
        return len(self)

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        hub: MessageHubProto[Message] | None = None,
        dispatcher: Dispatcher | None = None,
        children: Callable[[], Iterable[VM]] | None = None,
        hint: str = "",
        auto_construct_on_add: bool = False,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> GroupVM[VM]:
        """Construct a :class:`GroupVM` from keyword options in one call.

        An additive alternative to :class:`~vmx.groups.builders.GroupVMBuilder`
        (ADR-0055 / VMX-020). Delegates to that builder, so required-field
        validation (``BuilderValidationError`` on a missing
        ``name``/``hub``/``dispatcher``/``children``) and the resulting VM are identical to
        the fluent path. ``children`` is required (pass ``lambda: ()`` for an
        initially empty group).
        """
        from vmx.groups.builders import GroupVMBuilder

        builder: GroupVMBuilder[VM] = GroupVMBuilder()
        builder = (
            builder.hint(hint)
            .auto_construct_on_add(auto_construct_on_add)
            .destruct_order(destruct_order)
        )
        if children is not None:
            builder = builder.children(children)
        if name is not None:
            builder = builder.name(name)
        if hub is not None:
            builder = builder._option_hub(hub)
        if dispatcher is not None:
            builder = builder._option_dispatcher(dispatcher)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        if on_destruct is not None:
            builder = builder.on_destruct(on_destruct)
        return builder.build()


# ---------------------------------------------------------------------------
# _GroupParent — adaptor implementing _ParentCompositeVM for GroupVM
# ---------------------------------------------------------------------------


class _GroupParent(_ParentCompositeVM, Generic[VM]):
    """Thin adaptor so children can call ``_set_parent(parent)`` correctly.

    GroupVM has no selection: ``current_child`` is always ``None`` and
    ``select_child`` / ``deselect_child`` are deliberate no-ops.
    """

    def __init__(self, group: GroupVM[VM]) -> None:
        self._group = group

    @property
    def owner(self) -> _ComponentVMBase:
        return self._group

    @property
    def owner_parent(self) -> _ParentCompositeVM | None:
        return self._group._parent

    @property
    def current_child(self) -> object | None:
        return None

    @property
    def supports_child_selection(self) -> bool:
        # GroupVM has no selection slot — a group child's select() is a no-op,
        # so its select_command must report can_execute == False (VMX-077).
        return False

    def select_child(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM has no selection concept."""

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM has no selection concept."""

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        with self._group._membership_gate:
            identity = vm._ownership_identity
            return any(child._ownership_identity is identity for child in self._group._children)

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        with self._group._membership_gate:
            self._group._begin_membership_transaction_locked()
            index = next((i for i, child in enumerate(self._group._children) if child is vm), -1)
            if index < 0:
                self._group._membership_transaction_active = False
                self._group._membership_transaction_owner = None
                self._group._membership_condition.notify_all()
                raise RuntimeError("recorded parent does not contain child identity")
            child = self._group._children.pop(index)

        def commit() -> None:
            try:
                self._group._emit_collection_changed(
                    CollectionChangedEvent(action="remove", old_items=(child,), old_index=index)
                )
            finally:
                self._group._end_membership_transaction(
                    propagate_dispose_failure=sys.exc_info()[0] is None
                )

        def rollback() -> None:
            try:
                with self._group._membership_gate:
                    if self._group._dispose_requested:
                        child._set_parent(None)
                        return
                    self._group._children.insert(min(index, len(self._group._children)), child)
                    child._set_parent(self)
            finally:
                self._group._end_membership_transaction(propagate_dispose_failure=False)

        return _ParentTransfer(commit, rollback)
