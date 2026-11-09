"""CompositeVM (non-modeled) and CompositeVMOf[M, VM] (modeled composite).

See spec/06-composite-vm.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from functools import partial
from threading import Condition, RLock, get_ident
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import DisposableBase, SchedulerBase
from reactivex.subject import Subject

from vmx._disposal import _run_disposal_steps as _run_every_step
from vmx._indexes import _reject_bool_index
from vmx._subscriber_failures import FanOutSubject
from vmx._wait_for_graph import WAITS
from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.components._container_helpers import (
    attach_late_start_locked,
    auto_construct_attached,
    compensate_auto_construct,
    construct_walk,
    deliver_collection_changed,
    emit_collection_changed,
    enter_batch,
    exit_batch,
    finish_add_start,
    is_member,
    join_if_pending,
    maybe_auto_construct,
    seal_or_next_late,
)
from vmx.components._late_child_starts import (
    _LateChildStarts,
    _LateWalk,
    _StartRecord,
)
from vmx.components._unowned_candidates import dispose_unowned_candidates
from vmx.components.base import (
    _begin_parent_transfer,
    _commit_parent_transfer,
    _ComponentVMBase,
    _ownership_reservation_batch,
    _ParentCompositeVM,
    _ParentTransfer,
)
from vmx.components.child_order import ChildOrder, _in_destruct_order, _require_child_order
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHubProto

VM = TypeVar("VM", bound=_ComponentVMBase)
M = TypeVar("M")

_current_change_coordinator = RLock()

# The kinds of _CompositeVMBase._apply_current_change (spec/06 §4.3).
_CALL = "call"
_CHILD = "child"
_DELIVERY = "delivery"
_CLEAR = "clear"
_DISPOSE_CLEAR = "dispose-clear"


def _transaction_in_progress() -> RuntimeError:
    return RuntimeError("container membership transaction is already in progress")


def _selection_while_disposing() -> RuntimeError:
    return RuntimeError("cannot select a child while the container is disposing")


def _cannot_select(vm: object) -> ValueError:
    """The ``select_component`` predicate error (spec/06 §3.1)."""
    return ValueError(
        f"Cannot select '{getattr(vm, 'name', vm)!r}': can_select_component returned False."
    )


# ---------------------------------------------------------------------------
# _CompositeVMBase
# ---------------------------------------------------------------------------


class _CompositeVMBase(Generic[VM], _ComponentVMBase, _ParentCompositeVM):
    """Abstract base for all CompositeVM variants.

    Extends _ComponentVMBase with:
    - Ordered children list (MutableSequence semantics)
    - ``current`` selection slot
    - ``on_collection_changed`` Observable
    - Coordinated construct / destruct / dispose for child hierarchy
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str = "",
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> None:
        # Checked before any state exists: an unknown order is a caller error.
        _require_child_order(destruct_order)
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            on_construct=on_construct,
            on_destruct=on_destruct,
        )
        self._async_selection: bool = async_selection
        self._auto_construct_on_add: bool = auto_construct_on_add
        # Fixed at build time: the destruct walk and dispose cascade order (ADR-0161).
        self._destruct_order: ChildOrder = destruct_order
        self._children: list[VM] = []
        self._current: VM | None = None
        self._collection_changed_subject: Subject[CollectionChangedEvent] = FanOutSubject()
        self._populated: bool = False
        # Collects the children population started constructing (see _on_construct).
        self._population_joined: list[VM] | None = None
        self._batch_depth: int = 0
        self._batch_dirty: bool = False
        self._dispose_requested: bool = False
        self._dispose_deferred: bool = False
        self._active_current_publications: int = 0
        # The threads that publish a current change under the lease above. A
        # dispose from one of them defers to the lease: waiting there for
        # another thread's transaction could deadlock the selection
        # (spec/06 §3.2, #1064).
        self._current_publication_threads: list[int] = []
        self._membership_transaction_active: bool = False
        self._membership_transaction_owner: int | None = None
        # The child an in-flight add, insert or replacement attached and has
        # not admitted yet; a rollback may still remove it (#1064). Such a
        # child is not a member for selection (spec/06 §4.3 rule 2, ADR-0173).
        self._pending_admission: VM | None = None
        # The children an in-flight _attach_population attached and has not
        # committed yet; like _pending_admission, not members for selection.
        self._staged_population: tuple[VM, ...] | None = None
        # Set while the open membership transaction is uncommitted: its
        # rollback could still undo a staged attach, population or transfer
        # detach. The owner thread's selection calls are refused in that
        # window (spec/06 §4.3 rule 4). Cleared at the commit and when the
        # transaction ends.
        self._transaction_staged: bool = False
        self._membership_gate = RLock()
        # Start records of the children an auto-construct add attaches while
        # Constructing; the construct walk waits on them (spec/06 §5.1).
        self._late_starts = _LateChildStarts()
        self._membership_condition = Condition(self._membership_gate)
        self._current_selector: Callable[[Iterable[VM]], VM | None] | None = current_selector
        self._on_current_changed: Callable[[VM | None], None] | None = on_current_changed
        # Test-only seam: runs at the entry of _detach_clearing_current, before
        # the coordination lane (#1406). Production code never sets it.
        self._detach_probe_for_testing: Callable[[VM], None] | None = None

    # ── ViewModelType ─────────────────────────────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPOSITE

    # ── IParentCompositeVM implementation ─────────────────────────────────────

    @property
    def owner(self) -> _ComponentVMBase:
        return self

    @property
    def owner_parent(self) -> _ParentCompositeVM | None:
        return self._parent

    @property
    def current_child(self) -> object | None:
        with self._membership_gate:
            return self._current

    def select_child(self, vm: _ComponentVMBase) -> None:
        """The child ``select()`` path: every refusal is silent (ADR-0188).

        It runs the checks of ``select_component`` (spec/05 §6, spec/06 §3.1).
        A non-member, a member that is not Constructed, the caller's own
        uncommitted transaction, pending disposal and a check that fails at
        the commit change nothing and raise nothing. An async delivery drops
        a child that is no longer valid (#1220).
        """
        if isinstance(vm, _ComponentVMBase):
            for child in self.snapshot():
                if child is vm:
                    if child.status is not ConstructionStatus.CONSTRUCTED:
                        return
                    self._set_current(
                        child,
                        async_sel=self._async_selection,
                        require_constructed=True,
                        silent=True,
                    )
                    return

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        """The child ``deselect()`` path: every refusal is silent (ADR-0188)."""
        if self.current is vm:
            self._set_current(None, async_sel=self._async_selection, silent=True)

    def _child_disposed(self, vm: _ComponentVMBase) -> None:
        """Clear ``current`` after the current child published Disposed.

        The dispose clear of spec/06 §4.3 rule 9 (ADR-0189). It clears only
        while that child is still current, compared by ownership identity so
        a forwarding decorator matches. It never runs during this composite's
        own disposal: requested, deferred or Disposed. The commit checks that
        again, because the composite's dispose can start in between.
        """
        identity = vm._ownership_identity
        with self._membership_gate:
            if self._disposal_pending_locked() or self._status is ConstructionStatus.DISPOSED:
                return
            current = self._current
            if current is None or current._ownership_identity is not identity:
                return
        self._apply_current_change(None, kind=_DISPOSE_CLEAR, only_replacing=current)

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        with self._membership_gate:
            identity = vm._ownership_identity
            return any(child._ownership_identity is identity for child in self._children)

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        with self._membership_gate:
            self._begin_membership_transaction_locked()
            index = next((i for i, child in enumerate(self._children) if child is vm), -1)
            if index < 0:
                self._release_membership_transaction_locked()
                raise RuntimeError("recorded parent does not contain child identity")
            child = self._children.pop(index)
            was_current = self._current is child
            # The detach is staged until the transfer commits or rolls back
            # (spec/06 §4.3 rule 4).
            self._transaction_staged = True

        def commit() -> None:
            first_error: BaseException | None = None
            with self._membership_gate:
                self._transaction_staged = False
            try:
                if was_current:
                    self._apply_current_change(None, kind=_CLEAR, only_replacing=child)
            except BaseException as error:
                first_error = error
            try:
                self._emit_collection_changed(
                    CollectionChangedEvent(action="remove", old_items=(child,), old_index=index)
                )
            except BaseException as error:
                if first_error is None:
                    first_error = error
            try:
                self._end_membership_transaction(propagate_dispose_failure=first_error is None)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            if first_error is not None:
                raise first_error

        def rollback() -> None:
            try:
                with self._membership_gate:
                    if self._dispose_requested:
                        child._set_parent(None)
                        return
                    self._children.insert(min(index, len(self._children)), child)
                    child._set_parent(self)
            finally:
                self._end_membership_transaction(propagate_dispose_failure=False)

        return _ParentTransfer(commit, rollback)

    # ── on_collection_changed ─────────────────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedEvent]:
        """Observable that emits a CollectionChangedEvent on every mutation.

        The backing Subject is sealed behind ``as_observable`` so external
        callers can only subscribe — never ``on_next``/``dispose`` the internal
        stream (VMX-013).
        """
        return self._collection_changed_subject.pipe(ops.as_observable())

    def snapshot(self) -> tuple[VM, ...]:
        """Return the current ordered child-membership snapshot."""
        with self._membership_gate:
            return tuple(self._children)

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase:
        """Subscribe to payload-free structural child-membership pulses."""
        return self.on_collection_changed.subscribe(lambda _event: callback())

    # ── current property ─────────────────────────────────────────────────────

    @property
    def current(self) -> VM | None:
        """The currently selected child, or None."""
        with self._membership_gate:
            return self._current

    @current.setter
    def current(self, value: VM | None) -> None:
        """Set current selection without a membership transaction (spec/06 §4.3).

        - None is legal, also while disposal is pending.
        - Non-None must be an admitted child; raises ValueError otherwise.
          A child that an add or population attached but has not admitted is
          not a member yet.
        - Non-None raises RuntimeError while disposal is pending.
        - Any value raises RuntimeError inside the caller's own uncommitted
          membership transaction.
        - A Disposed child is not a member: it raises the non-member
          ValueError (ADR-0189).
        - After those checks, a non-None value while this composite is
          Destructing changes nothing and raises nothing (ADR-0188).
        - Another thread's membership transaction never fails or delays it.
        - If async_selection is True, validates now, then dispatches via the
          foreground scheduler; the delivery validates again.
        """
        self._set_current(value, async_sel=self._async_selection)

    # ── Selection methods ─────────────────────────────────────────────────────

    def select_component(self, vm: VM) -> None:
        """Select *vm* as current.  Raises if ``can_select_component`` is False.

        A call that only the Destructing rule refuses changes nothing and
        raises nothing (spec/06 §3.1, §4.3 rule 8, ADR-0188).
        """
        if not self._can_select_component(vm, destructing_refuses=False):
            raise _cannot_select(vm)
        # The commit checks Constructed again under its locks, so a destruct
        # on another thread after this check cannot pass it (#1220).
        self._set_current(vm, async_sel=self._async_selection, require_constructed=True)

    def deselect_component(self, vm: VM) -> None:
        """Deselect *vm*.  Raises if *vm* is not the current selection."""
        with self._membership_gate:
            # Every selection call fails inside the caller's own uncommitted
            # transaction (spec/06 §4.3 rule 4).
            if self._caller_owns_uncommitted_transaction_locked():
                raise _transaction_in_progress()
            if self._current is not vm:
                raise ValueError(
                    f"Cannot deselect '{getattr(vm, 'name', vm)!r}': "
                    "it is not the current selection."
                )
        self.current = None

    def can_select_component(self, vm: VM) -> bool:
        """Return True iff ``select_component(vm)`` would succeed now.

        *vm* is an admitted child and Constructed, no disposal of this
        composite is pending, the composite is not Destructing, and the caller
        is not inside its own uncommitted membership transaction (spec/06
        §3.1, ADR-0173, ADR-0188).
        """
        return self._can_select_component(vm, destructing_refuses=True)

    def _can_select_component(self, vm: VM | None, *, destructing_refuses: bool) -> bool:
        # A None vm from unchecked code is never a child (spec/06 §3.1, #1467).
        if vm is None or vm.status != ConstructionStatus.CONSTRUCTED:
            return False
        with self._membership_gate:
            return (
                not self._caller_owns_uncommitted_transaction_locked()
                and not self._disposal_pending_locked()
                and self._is_committed_member_locked(vm)
                and not (destructing_refuses and self._selection_silenced_locked(vm))
            )

    # ── MutableSequence-like collection API ───────────────────────────────────

    @property
    def count(self) -> int:
        """Number of children."""
        with self._membership_gate:
            return len(self._children)

    def __len__(self) -> int:
        with self._membership_gate:
            return len(self._children)

    def __iter__(self) -> Iterator[VM]:
        return iter(self.snapshot())

    def __contains__(self, item: object) -> bool:
        with self._membership_gate:
            return any(child is item for child in self._children)

    @overload
    def __getitem__(self, index: int) -> VM: ...

    @overload
    def __getitem__(self, index: slice) -> list[VM]: ...

    def __getitem__(self, index: int | slice) -> VM | list[VM]:
        with self._membership_gate:
            if isinstance(index, slice):
                return self._children[index]
            return self._children[index]

    def __setitem__(self, index: int, value: VM) -> None:
        _reject_bool_index(index)
        # Emit the actual position; a negative index counts from the end
        # (mirrors insert and ObservableList).
        if value is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        old: VM | None = None
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        succeeded = False
        try:
            original_status = value.status
            transfer = _begin_parent_transfer(value, self)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                resolved_index = index + len(self._children) if index < 0 else index
                # *old* keeps this composite as its parent until the commit,
                # which frees it and clears current in one locked section. No
                # other container can adopt it while it is still current here
                # (COMP-006), and a rollback can always put it back (#1219).
                old = self._children[index]
                self._children[index] = value
                value._set_parent(self)
                self._stage_admission_locked(value)
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
                    value._set_parent(None)
                self._pending_admission = None
                self._late_starts.remove(value, record)
            compensation_error = compensate_auto_construct(value, original_status)
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)
            # Admitted after the old parent's detach commit (COMP-006).
            self._admit_after_transfer_commit()

            def free_old_and_clear_current() -> None:
                self._detach_clearing_current(old)

            def raise_commit_error() -> None:
                if commit_error is not None:
                    raise commit_error

            # The change is committed: every publication step runs even when
            # an earlier one raises (e.g. on_current_changed), and the first
            # failure is re-raised.
            _run_every_step(
                raise_commit_error,
                free_old_and_clear_current,
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
            succeeded = True
        finally:
            try:
                self._end_membership_transaction(propagate_dispose_failure=succeeded)
            finally:
                # After the transaction ends (ADR-0218).
                finish_add_start(record)

    def __delitem__(self, index: int) -> None:
        self._remove_at(index)

    def index(self, value: VM, start: int = 0, stop: int | None = None) -> int:
        """Return the index of *value* in children."""
        children = self.snapshot()
        effective_stop = len(children) if stop is None else stop
        for index in range(*slice(start, effective_stop).indices(len(children))):
            if children[index] is value:
                return index
        raise ValueError(f"{value!r} is not in composite")

    def insert(self, index: int, item: VM) -> None:
        """Insert *item* before *index*, emitting a collection-changed event
        whose ``new_index`` is the actual insertion position (stdlib
        semantics: negatives count from the end, out-of-range clamps).
        """
        _reject_bool_index(index)
        if item is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        succeeded = False
        try:
            original_status = item.status
            transfer = _begin_parent_transfer(item, self)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                if index < 0:
                    index = max(index + len(self._children), 0)
                elif index > len(self._children):
                    index = len(self._children)
                self._children.insert(index, item)
                item._set_parent(self)
                attached = True
                self._stage_admission_locked(item)
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
                self._pending_admission = None
                self._late_starts.remove(item, record)
            compensation_error = compensate_auto_construct(item, original_status)
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)
            # Admitted after the old parent's detach commit (COMP-006).
            self._admit_after_transfer_commit()

            def raise_commit_error() -> None:
                if commit_error is not None:
                    raise commit_error

            # The add is committed: it publishes even when the transfer commit
            # failed, and the commit error re-raises first, as in the indexer
            # and population paths (#727, #1054).
            _run_every_step(
                raise_commit_error,
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(action="add", new_items=(item,), new_index=index)
                ),
            )
            succeeded = True
        finally:
            try:
                self._end_membership_transaction(propagate_dispose_failure=succeeded)
            finally:
                # After the transaction ends (ADR-0218).
                finish_add_start(record)

    def append(self, item: VM) -> None:
        """Append *item*, emitting a collection-changed event."""
        if item is None:
            raise ValueError("child must not be None")
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        original_status: ConstructionStatus | None = None
        record: _StartRecord | None = None
        succeeded = False
        try:
            original_status = item.status
            transfer = _begin_parent_transfer(item, self)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                self._children.append(item)
                item._set_parent(self)
                idx = len(self._children) - 1
                attached = True
                self._stage_admission_locked(item)
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
                self._pending_admission = None
                self._late_starts.remove(item, record)
            compensation_error = compensate_auto_construct(item, original_status)
            if transfer is not None:
                transfer.rollback()
            if compensation_error is not None:
                raise compensation_error from original_error
            raise
        else:
            commit_error = _commit_parent_transfer(transfer)
            # Admitted after the old parent's detach commit (COMP-006).
            self._admit_after_transfer_commit()

            def raise_commit_error() -> None:
                if commit_error is not None:
                    raise commit_error

            # The add is committed: it publishes even when the transfer commit
            # failed, and the commit error re-raises first, as in the indexer
            # and population paths (#727, #1054).
            _run_every_step(
                raise_commit_error,
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(action="add", new_items=(item,), new_index=idx)
                ),
            )
            succeeded = True
        finally:
            try:
                self._end_membership_transaction(propagate_dispose_failure=succeeded)
            finally:
                # After the transaction ends (ADR-0218).
                finish_add_start(record)

    def add(self, item: VM) -> None:
        """Alias for ``append``."""
        self.append(item)

    def remove(self, item: VM) -> bool:
        """Remove first occurrence of *item*.  Returns True on success."""
        self._begin_membership_transaction()
        succeeded = False
        try:
            with _current_change_coordinator:
                with self._membership_gate:
                    idx = next((i for i, child in enumerate(self._children) if child is item), -1)
                    if idx < 0:
                        succeeded = True
                        return False
                    removed, was_current = self._remove_at_locked(idx)
                if was_current:
                    previous_flag_changed = removed._commit_is_current(False)

            def finish_current() -> None:
                if was_current:
                    self._finish_current_change(
                        removed,
                        None,
                        previous_flag_changed=previous_flag_changed,
                        value_flag_changed=False,
                    )

            # The removal is committed: the collection event is emitted even
            # when on_current_changed raises; the first failure is re-raised.
            _run_every_step(
                finish_current,
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(action="remove", old_items=(removed,), old_index=idx)
                ),
            )
            succeeded = True
        finally:
            self._end_membership_transaction(propagate_dispose_failure=succeeded)
        return True

    def remove_at(self, index: int) -> None:
        """Remove child at *index*."""
        self._remove_at(index)

    def clear(self) -> None:
        """Remove all children, emitting a Reset event."""
        self._begin_membership_transaction()
        succeeded = False
        try:
            with _current_change_coordinator:
                with self._membership_gate:
                    previous = self._current
                    self._current = None
                    for child in self._children:
                        if child._parent is self:
                            child._set_parent(None)
                    self._children.clear()
                if previous is not None:
                    previous_flag_changed = previous._commit_is_current(False)

            def finish_current() -> None:
                if previous is not None:
                    self._finish_current_change(
                        previous,
                        None,
                        previous_flag_changed=previous_flag_changed,
                        value_flag_changed=False,
                    )

            # The clear is committed: the reset is emitted even when
            # on_current_changed raises; the first failure is re-raised.
            _run_every_step(
                finish_current,
                lambda: self._emit_collection_changed(CollectionChangedEvent(action="reset")),
            )
            succeeded = True
        finally:
            self._end_membership_transaction(propagate_dispose_failure=succeeded)

    def move(self, from_index: int, to_index: int) -> None:
        """Move an existing child to its final index without rewiring it."""
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

    def copy_to(self, target: list[VM], array_index: int) -> None:
        """Copy children into *target* starting at *array_index*.

        Validates first, like ``List<T>.CopyTo``: a negative index or a target
        too small for every child raises before anything is written.
        """
        children = self.snapshot()
        if isinstance(array_index, bool) or array_index < 0:
            raise IndexError(f"array_index {array_index!r} must be a non-negative int")
        if array_index + len(children) > len(target):
            raise IndexError("target is too small for the children")
        for i, child in enumerate(children):
            target[array_index + i] = child

    def _remove_at(self, index: int) -> None:
        _reject_bool_index(index)
        self._begin_membership_transaction()
        succeeded = False
        try:
            with _current_change_coordinator:
                with self._membership_gate:
                    resolved_index = index + len(self._children) if index < 0 else index
                    item, was_current = self._remove_at_locked(index)
                if was_current:
                    previous_flag_changed = item._commit_is_current(False)

            def finish_current() -> None:
                if was_current:
                    self._finish_current_change(
                        item,
                        None,
                        previous_flag_changed=previous_flag_changed,
                        value_flag_changed=False,
                    )

            # The removal is committed: the collection event is emitted even
            # when on_current_changed raises; the first failure is re-raised.
            _run_every_step(
                finish_current,
                lambda: self._emit_collection_changed(
                    CollectionChangedEvent(
                        action="remove", old_items=(item,), old_index=resolved_index
                    )
                ),
            )
            succeeded = True
        finally:
            self._end_membership_transaction(propagate_dispose_failure=succeeded)

    def _remove_at_locked(self, index: int) -> tuple[VM, bool]:
        item = self._children[index]
        del self._children[index]
        if item._parent is self:
            item._set_parent(None)
        was_current = self._current is item
        if was_current:
            self._current = None
        return item, was_current

    # ── Batch + auto-construct (spec v1.1) ────────────────────────────────────

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
        self,
        joined: list[VM],
        visited: dict[int, VM],
        walk: _LateWalk,
        commit: Callable[[], None],
    ) -> VM | None:
        return seal_or_next_late(self, joined, visited, walk, commit)

    def _validate_move_index(self, index: int) -> None:
        _reject_bool_index(index)
        if index < 0 or index >= len(self._children):
            raise IndexError(f"move index {index} out of range for {len(self._children)} children")

    # ── Lifecycle overrides ───────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate children (once) then call construct() on each.

        After all children reach Constructed, apply the optional initial-current
        selector (spec/06 §3.2, ADR-0042). The composite is still in Constructing
        here; every child is Constructed. The result goes through the
        non-raising validated assignment (ADR-0050, ADR-0165). None or a value
        that is not a committed member leaves current at its prior value
        (initially None), with no notification. So does a disposing composite.
        """
        super()._on_construct()
        # Children whose construct population started are joined, not restarted.
        joined: list[VM] = []
        if not self._populated:
            if self._population_superseded():
                return
            initial_count = len(self._children)
            self._population_joined = joined
            try:
                self._populate_children()
            except Exception:
                if not self._populated:
                    while len(self._children) > initial_count:
                        self._remove_at(len(self._children) - 1)
                raise
            finally:
                self._population_joined = None
            self._populated = True

        def apply_initial_current() -> None:
            if self._current_selector is None:
                return
            initial = self._current_selector(self)
            if initial is not None:
                self._apply_selector_result(initial)

        # This walk's scope of start records, begun before its snapshot.
        # The walk counts members only (ADR-0186).
        member = partial(is_member, self)
        walk = self._late_starts.begin_walk(self, member)
        visited: dict[int, VM] = {}
        # The commit step is bound to this hook's walk (ADR-0186, #1374).
        commit = self._construct_commit_for_running_hook()
        walking = self._transition_container_children(
            self._construct_walk(joined, visited, walk),
            construct=True,
            after=apply_initial_current,
            joined=joined,
            join=walk.join,
            seal=(
                (lambda: self._seal_or_next_late(joined, visited, walk, commit))
                if self._auto_construct_on_add
                else None
            ),
            is_member=member,
        )

        # A failed walk ends its own scope when it fails, not at a later GC.
        walking.add_done_callback(lambda _: walk.end())
        self._complete_lifecycle_hook_after(walking)

    def _on_destruct(self) -> None:
        """Set current=None then destruct all children in the destruct order.

        The clear opens no membership transaction and is never refused, so it
        also runs while another thread holds a transaction, inside this
        composite's own transaction and while disposal is deferred
        (spec/06 §5, ADR-0173).
        """
        self._apply_current_change(None, kind=_CLEAR)
        if self._is_disposed():
            # A disposal from the clear's callbacks ran when the lease ended.
            # Like a C# walk whose owner is disposed, the walk destructs no
            # child and the user on_destruct does not run after dispose (#735).
            return
        self._complete_lifecycle_hook_after(
            self._transition_children(
                _in_destruct_order(self.snapshot(), self._destruct_order),
                construct=False,
                after=super()._on_destruct,
            )
        )

    def dispose(self) -> None:
        """Dispose cascade (LIFE-013): depth-first dispose each child, then self."""
        with self._membership_condition:
            if self._dispose_requested:
                return
            if get_ident() in self._current_publication_threads:
                self._dispose_deferred = True
                return
            if not self._wait_for_foreign_transaction_locked():
                return
            if self._membership_transaction_active or self._active_current_publications > 0:
                self._dispose_deferred = True
                return
            self._dispose_requested = True
            snapshot = _in_destruct_order(self._children, self._destruct_order)
        # The cascade runs at the base's admitted-hook boundary (LIFE-015): a
        # foreign dispose cleans no child while this container's hook runs. No
        # lock is held here, so the hook can finish while this call waits.
        self._dispose_with_children(snapshot)

    def _population_superseded(self) -> bool:
        """Whether a dispose() superseded the construct hook before population.

        Factory population is a post-hook container action. A superseded hook
        calls no children factory and attaches nothing, and construct()
        returns without an error (spec/02 §2.4, LIFE-015, ADR-0218).
        """
        with self._membership_gate:
            if self._dispose_requested:
                return True
        return self._is_disposed()

    def _require_child_admission(self) -> None:
        if self._dispose_requested or self._dispose_deferred:
            raise RuntimeError("cannot attach a child while the container is disposing")
        if self._membership_transaction_active:
            raise RuntimeError("container membership transaction is already in progress")

    def _begin_membership_transaction_locked(self) -> None:
        self._require_child_admission()
        self._membership_transaction_active = True
        self._membership_transaction_owner = get_ident()
        WAITS.acquire(self._membership_gate, get_ident())

    def _release_membership_transaction_locked(self) -> None:
        self._membership_transaction_active = False
        self._membership_transaction_owner = None
        WAITS.release(self._membership_gate)
        self._membership_condition.notify_all()

    def _wait_for_foreign_transaction_locked(self) -> bool:
        """Wait while another thread owns the membership transaction (ADR-0122).

        A wait that would close a wait-for cycle records the disposal for the
        transaction owner instead, which disposes this container when its
        transaction ends (ADR-0153). Return False when the caller has nothing
        left to do.
        """
        caller = get_ident()
        while self._membership_transaction_active and self._membership_transaction_owner != caller:
            if not WAITS.try_begin_wait(self._membership_gate, caller):
                self._dispose_deferred = True
                return False
            try:
                self._membership_condition.wait()
            finally:
                WAITS.end_wait(caller)
            if self._dispose_requested:
                return False
        return True

    def _require_transaction_can_continue_locked(self) -> None:
        if self._dispose_requested or self._dispose_deferred:
            raise RuntimeError("cannot attach a child while the container is disposing")

    def _begin_membership_transaction(self) -> None:
        with self._membership_gate:
            self._begin_membership_transaction_locked()

    def _end_membership_transaction(self, *, propagate_dispose_failure: bool = True) -> None:
        """End the transaction and run a deferred dispose().

        The caller passes whether its operation succeeded as an explicit flag.
        ``sys.exc_info()`` cannot tell: it also reports an exception that a
        caller frame handles, such as an ``except`` block or the child walk
        around an on_destruct hook (#1152). A failed operation keeps its own
        error as the first failure (spec/06 §4.2).
        """
        with self._membership_condition:
            self._release_membership_transaction_locked()
            self._transaction_staged = False
            # The deferral stays set until dispose() admits it, so no transaction
            # or selection starts between this release and dispose() (#1064).
            dispose = self._dispose_deferred and self._active_current_publications == 0
        if dispose:
            try:
                self.dispose()
            except BaseException:
                if propagate_dispose_failure:
                    raise

    def _end_current_publication(self, *, propagate_dispose_failure: bool) -> None:
        with self._membership_condition:
            self._active_current_publications -= 1
            self._current_publication_threads.remove(get_ident())
            dispose = (
                self._active_current_publications == 0
                and not self._membership_transaction_active
                and self._dispose_deferred
            )
            # The deferral stays set until dispose() admits it (#1064).
            self._membership_condition.notify_all()
        if dispose:
            try:
                self.dispose()
            except BaseException:
                if propagate_dispose_failure:
                    raise

    def _on_dispose(self) -> None:
        """Complete and dispose the collection_changed subject."""
        subject = self._collection_changed_subject
        if not subject.is_disposed:
            # A raising completion observer must not skip the dispose (#1072).
            _run_every_step(subject.on_completed, subject.dispose)

    # ── Factory hook (overridden by subclasses) ───────────────────────────────

    def _populate_children(self) -> None:
        """Called once during construct() to add children from factory.

        Default: no-op (children were added manually via append/insert/etc.).
        Subclasses override to evaluate their factory.
        """

    def _join_if_pending(self, child: VM) -> None:
        join_if_pending(self, child)

    def _attach_population(self, children: Iterable[VM]) -> None:
        """Attach one factory population as an all-or-nothing transaction.

        Until the population commits, its candidates are not members for
        selection: the ``current`` setter raises ValueError and the construct
        walk's assignment ignores them (spec/06 §4.3, ADR-0173).
        """
        candidates = list(children)
        if len({id(child._ownership_identity) for child in candidates}) != len(candidates):
            raise ValueError(
                "factory population contains a duplicate child identity "
                "(duplicate canonical child identity)"
            )
        self._begin_membership_transaction()
        transfers: list[_ParentTransfer | None] = []
        original_statuses: list[ConstructionStatus] = []
        parent: _ParentCompositeVM = self
        succeeded = False
        try:
            with _ownership_reservation_batch(candidates):
                for child in candidates:
                    transfer = _begin_parent_transfer(child, parent)
                    transfers.append(transfer)
                    original_statuses.append(child.status)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                for child in candidates:
                    self._children.append(child)
                    child._set_parent(parent)
                self._staged_population = tuple(candidates)
                self._transaction_staged = True

            # Populate the complete snapshot before invoking any child hook,
            # but never execute user lifecycle hooks while holding the
            # destination membership gate.
            for child in candidates:
                if (
                    self.status is ConstructionStatus.CONSTRUCTING
                    and child.status is not ConstructionStatus.CONSTRUCTED
                ):
                    child.construct()
                    self._join_if_pending(child)
                else:
                    self._maybe_auto_construct(child)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            for child, original_status in reversed(
                list(zip(candidates, original_statuses, strict=False))
            ):
                with self._membership_gate:
                    if any(candidate is child for candidate in self._children):
                        self._children.remove(child)
                # Detached first: a deferred compensation destructs only a
                # child with no parent (ADR-0218 rule 7).
                if child._parent is parent:
                    child._set_parent(None)
                error = compensate_auto_construct(child, original_status)
                if compensation_error is None:
                    compensation_error = error
            # Every candidate is detached: none is left to select (rule 2).
            with self._membership_gate:
                self._staged_population = None
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
            # Admitted after the old parents' detach commits (COMP-006).
            self._admit_after_transfer_commit()
            self._populated = True
            population_error = commit_error

            def raise_commit_error() -> None:
                if population_error is not None:
                    raise population_error

            def publish_add(child: VM) -> None:
                index = next(
                    (i for i, candidate in enumerate(self.snapshot()) if candidate is child),
                    -1,
                )
                if index >= 0:
                    self._emit_collection_changed(
                        CollectionChangedEvent(
                            action="add",
                            new_items=(child,),
                            new_index=index,
                        )
                    )

            # Every committed child publishes, even after a raising subscriber;
            # the first failure is re-raised (#727).
            _run_every_step(
                raise_commit_error,
                *(lambda child=child: publish_add(child) for child in candidates),
            )
            succeeded = True
        finally:
            self._end_membership_transaction(propagate_dispose_failure=succeeded)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _stage_admission_locked(self, item: VM) -> None:
        """Mark *item* attached but not admitted (spec/06 §4.3 rules 2 and 4)."""
        self._pending_admission = item
        self._transaction_staged = True

    def _admit_locked(self) -> None:
        """Admit the staged child or population (spec/06 §4.3 rules 2 and 4).

        It becomes a member for selection before collection-changed
        publishes, and the owner thread may select again.
        """
        self._pending_admission = None
        self._staged_population = None
        self._transaction_staged = False

    def _admit_after_transfer_commit(self) -> None:
        """Admit the staged child or population after the transfer commits.

        It runs after the old parents' detach commits and before
        collection-changed (spec/06 §4.3 rule 2). An earlier admission would
        let another thread select a moved child here while the old parent's
        detach clear can still reset its ``is_current`` flag (COMP-006).
        """
        with self._membership_gate:
            self._admit_locked()

    def _disposal_pending_locked(self) -> bool:
        return self._dispose_requested or self._dispose_deferred

    def _is_committed_member_locked(self, value: VM) -> bool:
        """Contained, and not staged by an add or population (rule 2)."""
        staged = self._staged_population
        return (
            value is not self._pending_admission
            and (staged is None or not any(child is value for child in staged))
            and any(child is value for child in self._children)
        )

    def _caller_owns_uncommitted_transaction_locked(self) -> bool:
        """The caller owns this composite's uncommitted transaction (rule 4)."""
        return (
            self._transaction_staged
            and self._membership_transaction_active
            and self._membership_transaction_owner == get_ident()
        )

    def _selection_refusal_locked(
        self, value: VM | None, *, disposed: bool, require_constructed: bool = False
    ) -> Exception | None:
        """The refusal of a selection of *value*, or None (spec/06 §4.3 rules 2-4).

        *require_constructed* (``select_component`` and ``select_child``) also
        refuses a child that is not Constructed now, with the predicate error
        (spec/06 §3.1). The check runs at the commit, so a destruct after the
        entry check cannot pass it (#1220, #1229).

        *disposed* keeps the post-dispose behavior: a null clear that would
        change a disposed composite raises, as it always has (chapter 01 §4).
        After Disposed, re-assigning the child that is already current changes
        nothing and stays the no-op it always was; while disposal is only
        requested or deferred, it is refused like any non-null selection
        (rule 3).
        """
        if self._caller_owns_uncommitted_transaction_locked():
            return _transaction_in_progress()
        if value is None:
            return _selection_while_disposing() if disposed and self._current is not None else None
        if self._disposal_pending_locked():
            return None if disposed and value is self._current else _selection_while_disposing()
        # A Disposed child is not a member for selection (spec/06 §4.3 rule 2,
        # ADR-0189).
        if (
            not self._is_committed_member_locked(value)
            or value.status is ConstructionStatus.DISPOSED
        ):
            return ValueError(
                f"Cannot set current to '{getattr(value, 'name', value)!r}': "
                "it is not a member of this composite."
            )
        if require_constructed and value.status is not ConstructionStatus.CONSTRUCTED:
            return _cannot_select(value)
        return None

    def _selection_silenced_locked(self, value: VM | None) -> bool:
        """A non-null selection while this composite is Destructing (rule 8).

        Checked after the refusals of rules 2, 3 and 4, which keep their
        errors. It changes nothing and raises nothing (ADR-0188). The status
        is Destructing before the destruct clear runs, so this read under the
        membership gate never lets a selection outlive the clear.
        """
        return value is not None and self._status is ConstructionStatus.DESTRUCTING

    def _set_current(
        self,
        value: VM | None,
        *,
        async_sel: bool,
        require_constructed: bool = False,
        silent: bool = False,
    ) -> None:
        """Apply the current change, optionally dispatching via foreground.

        *silent* (the child ``select`` and ``deselect`` paths) turns every
        refusal into a no-op (ADR-0188).
        """
        if not async_sel:
            self._apply_current_change(
                value, kind=_CHILD if silent else _CALL, require_constructed=require_constructed
            )
            return
        # The call validates now and raises as the synchronous setter does;
        # the delivery validates again (spec/06 §4.3 rule 7).
        disposed = self._is_disposed()
        with self._membership_gate:
            refusal = self._selection_refusal_locked(
                value, disposed=disposed, require_constructed=require_constructed
            )
            silenced = self._selection_silenced_locked(value)
        if refusal is not None:
            if silent:
                return
            raise refusal
        if silenced:
            return
        captured = value

        def _dispatch(scheduler: SchedulerBase, state: object | None) -> None:
            self._apply_current_change(
                captured, kind=_DELIVERY, require_constructed=require_constructed
            )

        self._dispatcher.foreground.schedule(_dispatch)

    def _apply_current_change(
        self,
        value: VM | None,
        *,
        kind: str,
        only_replacing: VM | None = None,
        require_constructed: bool = False,
    ) -> None:
        """Change ``current`` without a membership transaction (spec/06 §4.3).

        Validation and the commit of ``current`` and both ``is_current`` flags
        run under the coordination lane and the membership gate; another
        thread's transaction neither fails nor delays it. The publication runs
        after both are released, under the current-publication lease, so a
        dispose from the callbacks is deferred until they return. *kind* is
        ``_CALL`` (a refusal raises), ``_CHILD`` (the child ``select`` and
        ``deselect`` paths: a refusal is a silent no-op, ADR-0188),
        ``_DELIVERY`` (an async delivery or the walk's assignment: a refusal
        is a silent no-op), ``_CLEAR`` (the destruct or detach clear: never
        refused) or ``_DISPOSE_CLEAR`` (the dispose clear: skipped while this
        composite's own disposal is pending or done, ADR-0189 rule 6). A
        non-null selection while the composite is Destructing changes nothing
        for every kind (rule 8). With *only_replacing*, the change applies
        only while that child is still current: a transaction clears the child
        it detached, never a selection made after the detach (#1064).
        """
        clear = kind in (_CLEAR, _DISPOSE_CLEAR)
        if clear:
            # A clear with nothing to clear skips the global lane.
            with self._membership_gate:
                if self._current is None:
                    return
        disposed = not clear and self._is_disposed()
        with _current_change_coordinator:
            with self._membership_gate:
                if kind == _DISPOSE_CLEAR and (
                    self._disposal_pending_locked() or self._status is ConstructionStatus.DISPOSED
                ):
                    return
                if not clear:
                    refusal = self._selection_refusal_locked(
                        value, disposed=disposed, require_constructed=require_constructed
                    )
                    if refusal is not None:
                        if kind == _CALL:
                            raise refusal
                        return
                    if self._selection_silenced_locked(value):
                        return
                previous = self._current
                if previous is value or (
                    only_replacing is not None and previous is not only_replacing
                ):
                    return
                self._current = value
                previous_flag_changed = (
                    previous._commit_is_current(False) if previous is not None else False
                )
                value_flag_changed = value._commit_is_current(True) if value is not None else False
                self._active_current_publications += 1
                self._current_publication_threads.append(get_ident())
        try:
            self._finish_current_change(
                previous,
                value,
                previous_flag_changed=previous_flag_changed,
                value_flag_changed=value_flag_changed,
            )
        except BaseException:
            self._end_current_publication(propagate_dispose_failure=False)
            raise
        # An explicit flag: callers such as the walk run inside an except
        # clause, so sys.exc_info() cannot tell success from failure (#1152).
        self._end_current_publication(propagate_dispose_failure=True)

    def _detach_clearing_current(self, detached: VM) -> None:
        """Free *detached* and clear it as current in one locked section (#1219).

        Under the coordination lane and the membership gate, *detached* loses
        this composite as its parent and, while it is still current, the same
        section clears ``current`` and its flag (spec/06 §4.3 rule 6). No
        other composite can adopt and select the child in between, so the
        clear never resets the flag of a selection elsewhere (COMP-006). The
        publication runs after both locks are released, under the
        current-publication lease, as in :meth:`_apply_current_change`.
        """
        probe = self._detach_probe_for_testing
        if probe is not None:
            probe(detached)
        with _current_change_coordinator:
            with self._membership_gate:
                if detached._parent is self:
                    detached._set_parent(None)
                if self._current is not detached:
                    return
                self._current = None
                previous_flag_changed = detached._commit_is_current(False)
                self._active_current_publications += 1
                self._current_publication_threads.append(get_ident())
        try:
            self._finish_current_change(
                detached,
                None,
                previous_flag_changed=previous_flag_changed,
                value_flag_changed=False,
            )
        except BaseException:
            self._end_current_publication(propagate_dispose_failure=False)
            raise
        self._end_current_publication(propagate_dispose_failure=True)

    def _apply_selector_result(self, value: VM) -> None:
        """Assign the Current(selector) result of a construct walk (#1064).

        The non-raising validated assignment of spec/06 §3.2 (ADR-0165,
        ADR-0173). It is a silent no-op while the composite is disposing,
        when *value* is not a committed member (not contained, or staged by an
        add or population whose rollback could still remove it), and on a
        thread that owns this composite's uncommitted transaction.
        """
        self._apply_current_change(value, kind=_DELIVERY)

    def _finish_current_change(
        self,
        previous: VM | None,
        value: VM | None,
        *,
        previous_flag_changed: bool,
        value_flag_changed: bool,
    ) -> None:
        """Publish one committed selection change outside the membership gate."""

        # Update IsCurrent on affected children.
        if previous is not None and previous_flag_changed:
            previous._publish_is_current()
        if value is not None and value_flag_changed:
            value._publish_is_current()

        # Emit PropertyChangedMessage("current") on the hub.
        self._notify_property_changed("current")

        # Invoke the optional builder-registered on_current_changed callback
        # AFTER state update + hub publish + INPC raise so every observer sees
        # the new value consistently (spec/06 §3.2, ADR-0042 §5.2).
        if self._on_current_changed is not None:
            self._on_current_changed(value)


# ---------------------------------------------------------------------------
# CompositeVM — non-modeled composite
# ---------------------------------------------------------------------------


class CompositeVM(Generic[VM], _CompositeVMBase[VM]):
    """Non-modeled composite viewmodel.

    Children are supplied by an optional factory ``() -> Iterable[VM]``
    evaluated lazily on the first ``construct()``.

    Use ``CompositeVM.builder()`` to create instances.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str = "",
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        children_factory: Callable[[], Iterable[VM]] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            async_selection=async_selection,
            auto_construct_on_add=auto_construct_on_add,
            on_construct=on_construct,
            on_destruct=on_destruct,
            current_selector=current_selector,
            on_current_changed=on_current_changed,
            destruct_order=destruct_order,
        )
        self._children_factory: Callable[[], Iterable[VM]] | None = children_factory

    @staticmethod
    def builder() -> CompositeVMBuilder[VM]:
        """Return a new immutable builder for :class:`CompositeVM`."""
        return CompositeVMBuilder()

    @classmethod
    def create(
        cls,
        *,
        name: str | None = None,
        hub: MessageHubProto[Message] | None = None,
        dispatcher: Dispatcher | None = None,
        children: Callable[[], Iterable[VM]] | None = None,
        hint: str = "",
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        current: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> CompositeVM[VM]:
        """Construct a :class:`CompositeVM` from keyword options in one call.

        An additive alternative to :meth:`builder` (ADR-0055 / VMX-020).
        Delegates to :class:`CompositeVMBuilder`, so required-field validation
        (``BuilderValidationError`` on a missing ``name``/``hub``/``dispatcher``/
        ``children``)
        and the resulting VM are identical to the fluent path. ``children`` is
        required (pass ``lambda: ()`` for an initially empty composite).
        """
        builder: CompositeVMBuilder[VM] = CompositeVMBuilder()
        builder = (
            builder.hint(hint)
            .async_selection(async_selection)
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
        if current is not None:
            builder = builder.current(current)
        if on_current_changed is not None:
            builder = builder.on_current_changed(on_current_changed)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        if on_destruct is not None:
            builder = builder.on_destruct(on_destruct)
        return builder.build()

    def _populate_children(self) -> None:
        if self._children_factory is None:
            return
        self._attach_population(self._children_factory())


# ---------------------------------------------------------------------------
# CompositeVMOf — modeled composite
# ---------------------------------------------------------------------------


class CompositeVMOf(Generic[M, VM], _CompositeVMBase[VM]):
    """Modeled composite viewmodel.

    Children are produced by:
    1. Evaluating ``children_models()`` to get an ``Iterable[M]``.
    2. Mapping each ``M`` via ``child_model_to_child_vm(m)`` to a ``VM``.

    Use ``CompositeVMOf.builder()`` to create instances.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str = "",
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        children_models: Callable[[], Iterable[M]],
        child_model_to_child_vm: Callable[[M], VM],
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
        destruct_order: ChildOrder = ChildOrder.INSERTION,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
            async_selection=async_selection,
            auto_construct_on_add=auto_construct_on_add,
            on_construct=on_construct,
            on_destruct=on_destruct,
            current_selector=current_selector,
            on_current_changed=on_current_changed,
            destruct_order=destruct_order,
        )
        self._children_models: Callable[[], Iterable[M]] = children_models
        self._child_model_to_child_vm: Callable[[M], VM] = child_model_to_child_vm

    @staticmethod
    def builder() -> CompositeVMOfBuilder[M, VM]:
        """Return a new immutable builder for :class:`CompositeVMOf`."""
        return CompositeVMOfBuilder()

    def _populate_children(self) -> None:
        # A projector that raises disposes the children it already built
        # (#1324); the composite keeps no children.
        children: list[VM] = []
        try:
            for model in self._children_models():
                children.append(self._child_model_to_child_vm(model))
        except BaseException:
            dispose_unowned_candidates(self, children)
            raise
        self._attach_population(children)


# Deferred import to avoid circular references.
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder  # noqa: E402
