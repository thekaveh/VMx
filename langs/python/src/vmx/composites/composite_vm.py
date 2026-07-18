"""CompositeVM (non-modeled) and CompositeVMOf[M, VM] (modeled composite).

See spec/06-composite-vm.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from threading import Condition, RLock, get_ident
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import DisposableBase, SchedulerBase
from reactivex.subject import Subject

from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.components.base import (
    _begin_parent_transfer,
    _ComponentVMBase,
    _dispose_children_then_self,
    _ParentCompositeVM,
    _ParentTransfer,
)
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

VM = TypeVar("VM", bound=_ComponentVMBase)
M = TypeVar("M")


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
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
    ) -> None:
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
        self._children: list[VM] = []
        self._current: VM | None = None
        self._collection_changed_subject: Subject[CollectionChangedEvent] = Subject()
        self._populated: bool = False
        self._batch_depth: int = 0
        self._batch_dirty: bool = False
        self._dispose_requested: bool = False
        self._dispose_deferred: bool = False
        self._membership_transaction_active: bool = False
        self._membership_transaction_owner: int | None = None
        self._membership_gate = RLock()
        self._membership_condition = Condition(self._membership_gate)
        self._current_selector: Callable[[Iterable[VM]], VM | None] | None = current_selector
        self._on_current_changed: Callable[[VM | None], None] | None = on_current_changed

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
        if isinstance(vm, _ComponentVMBase):
            # Use typed access via _set_current
            for child in self.snapshot():
                if child is vm:
                    self._set_current(child, async_sel=self._async_selection)
                    return

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        if self.current is vm:
            self._set_current(None, async_sel=self._async_selection)

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        with self._membership_gate:
            return any(child is vm for child in self._children)

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        with self._membership_gate:
            self._begin_membership_transaction_locked()
            index = next((i for i, child in enumerate(self._children) if child is vm), -1)
            if index < 0:
                self._membership_transaction_active = False
                self._membership_transaction_owner = None
                self._membership_condition.notify_all()
                raise RuntimeError("recorded parent does not contain child identity")
            child = self._children.pop(index)
            was_current = self._current is child

        def commit() -> None:
            try:
                if was_current:
                    self._apply_current_change(None, internal=True)
                self._emit_collection_changed(
                    CollectionChangedEvent(action="remove", old_items=(child,), old_index=index)
                )
            finally:
                self._end_membership_transaction()

        def rollback() -> None:
            try:
                with self._membership_gate:
                    if self._dispose_requested:
                        child._set_parent(None)
                        return
                    self._children.insert(min(index, len(self._children)), child)
                    child._set_parent(self)
            finally:
                self._end_membership_transaction()

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
        """Set current selection.

        - None is always legal.
        - Non-None must be in children; raises ValueError otherwise.
        - If async_selection is True, dispatches via foreground scheduler.
        """
        if value is not None and not any(child is value for child in self.snapshot()):
            raise ValueError(
                f"Cannot set current to '{getattr(value, 'name', value)!r}': "
                "it is not a member of this composite."
            )
        self._set_current(value, async_sel=self._async_selection)

    # ── Selection methods ─────────────────────────────────────────────────────

    def select_component(self, vm: VM) -> None:
        """Select *vm* as current.  Raises if ``can_select_component`` is False."""
        if not self.can_select_component(vm):
            raise ValueError(
                f"Cannot select '{getattr(vm, 'name', vm)!r}': can_select_component returned False."
            )
        self.current = vm

    def deselect_component(self, vm: VM) -> None:
        """Deselect *vm*.  Raises if *vm* is not the current selection."""
        if self.current is not vm:
            raise ValueError(
                f"Cannot deselect '{getattr(vm, 'name', vm)!r}': it is not the current selection."
            )
        self.current = None

    def can_select_component(self, vm: VM) -> bool:
        """Return True iff *vm* is in children and Status == Constructed."""
        return any(child is vm for child in self.snapshot()) and (
            vm.status == ConstructionStatus.CONSTRUCTED
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
        # Emit the actual position; a negative index counts from the end
        # (mirrors insert and ObservableList).
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        old: VM | None = None
        try:
            transfer = _begin_parent_transfer(value, self)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                resolved_index = index + len(self._children) if index < 0 else index
                old = self._children[index]
                self._children[index] = value
                old._set_parent(None)
                value._set_parent(self)
            self._maybe_auto_construct(value)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException:
            with self._membership_gate:
                if old is not None and any(child is value for child in self._children):
                    actual_index = next(
                        i for i, child in enumerate(self._children) if child is value
                    )
                    self._children[actual_index] = old
                    old._set_parent(self)
                    value._set_parent(None)
            if transfer is not None:
                transfer.rollback()
            raise
        else:
            if transfer is not None:
                transfer.commit()
            if self.current is old:
                self._apply_current_change(None, internal=True)
            self._emit_collection_changed(
                CollectionChangedEvent(action="remove", old_items=(old,), old_index=resolved_index)
            )
            self._emit_collection_changed(
                CollectionChangedEvent(action="add", new_items=(value,), new_index=resolved_index)
            )
        finally:
            self._end_membership_transaction()

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
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        try:
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
            self._maybe_auto_construct(item)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException:
            with self._membership_gate:
                if attached and any(child is item for child in self._children):
                    self._children.remove(item)
                    item._set_parent(None)
            if transfer is not None:
                transfer.rollback()
            raise
        else:
            if transfer is not None:
                transfer.commit()
            self._emit_collection_changed(
                CollectionChangedEvent(action="add", new_items=(item,), new_index=index)
            )
        finally:
            self._end_membership_transaction()

    def append(self, item: VM) -> None:
        """Append *item*, emitting a collection-changed event."""
        self._begin_membership_transaction()
        transfer: _ParentTransfer | None = None
        attached = False
        try:
            transfer = _begin_parent_transfer(item, self)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                self._children.append(item)
                item._set_parent(self)
                idx = len(self._children) - 1
                attached = True
            self._maybe_auto_construct(item)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
        except BaseException:
            with self._membership_gate:
                if attached and any(child is item for child in self._children):
                    self._children.remove(item)
                    item._set_parent(None)
            if transfer is not None:
                transfer.rollback()
            raise
        else:
            if transfer is not None:
                transfer.commit()
            self._emit_collection_changed(
                CollectionChangedEvent(action="add", new_items=(item,), new_index=idx)
            )
        finally:
            self._end_membership_transaction()

    def add(self, item: VM) -> None:
        """Alias for ``append``."""
        self.append(item)

    def remove(self, item: VM) -> bool:
        """Remove first occurrence of *item*.  Returns True on success."""
        with self._membership_gate:
            self._require_child_admission()
            idx = next((i for i, child in enumerate(self._children) if child is item), -1)
            if idx < 0:
                return False
            removed, was_current = self._remove_at_locked(idx)
            if was_current:
                self._finish_current_change(removed, None)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(removed,), old_index=idx)
        )
        return True

    def remove_at(self, index: int) -> None:
        """Remove child at *index*."""
        self._remove_at(index)

    def clear(self) -> None:
        """Remove all children, emitting a Reset event."""
        with self._membership_gate:
            self._require_child_admission()
            previous = self._current
            self._current = None
            for child in self._children:
                if child._parent is self:
                    child._set_parent(None)
            self._children.clear()
            # Keep child flags and observers serialized with the membership state.
            if previous is not None:
                self._finish_current_change(previous, None)
        self._emit_collection_changed(CollectionChangedEvent(action="reset"))

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
        """Copy children into *target* starting at *array_index*."""
        for i, child in enumerate(self.snapshot()):
            target[array_index + i] = child

    def _remove_at(self, index: int) -> None:
        with self._membership_gate:
            resolved_index = index + len(self._children) if index < 0 else index
            self._require_child_admission()
            item, was_current = self._remove_at_locked(index)
            if was_current:
                self._finish_current_change(item, None)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(item,), old_index=resolved_index)
        )

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
        self._batch_depth += 1
        return BatchUpdateHandle(self)

    def _exit_batch(self) -> None:
        self._batch_depth -= 1
        if (
            self._batch_depth == 0
            and self._batch_dirty
            and not self._collection_changed_subject.is_disposed
        ):
            self._batch_dirty = False
            self._collection_changed_subject.on_next(CollectionChangedEvent(action="reset"))

    def _emit_collection_changed(self, event: CollectionChangedEvent) -> None:
        # reactivex raises on post-dispose on_next (rxjs/Combine no-op); a
        # collection mutation after dispose must be inert, not throw.
        if self._collection_changed_subject.is_disposed:
            return
        if self._batch_depth > 0:
            self._batch_dirty = True
            return
        self._collection_changed_subject.on_next(event)

    def _maybe_auto_construct(self, child: VM) -> None:
        if not self._auto_construct_on_add:
            return
        if self._status != ConstructionStatus.CONSTRUCTED:
            return
        if child.status == ConstructionStatus.CONSTRUCTED:
            return
        child.construct()

    def _validate_move_index(self, index: int) -> None:
        if index < 0 or index >= len(self._children):
            raise IndexError(f"move index {index} out of range for {len(self._children)} children")

    # ── Lifecycle overrides ───────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate children (once) then call construct() on each.

        After all children reach Constructed, apply the optional initial-current
        selector (spec/06 §3.2, ADR-0042). The composite is still in Constructing
        here; every child is Constructed. A selector returning None or an
        out-of-set value leaves current at its prior value (initially None) and
        emits no notification — matching the select_component semantics.
        """
        super()._on_construct()
        if not self._populated:
            initial_count = len(self._children)
            try:
                self._populate_children()
            except Exception:
                while len(self._children) > initial_count:
                    self._remove_at(len(self._children) - 1)
                raise
            self._populated = True

        def apply_initial_current() -> None:
            if self._current_selector is None:
                return
            initial = self._current_selector(self)
            if initial is not None and any(child is initial for child in self.snapshot()):
                self._set_current(initial, async_sel=False)

        self._complete_lifecycle_hook_after(
            self._transition_children(
                list(self.snapshot()),
                construct=True,
                after=apply_initial_current,
            )
        )

    def _on_destruct(self) -> None:
        """Set current=None then destruct all children."""
        if self.current is not None:
            self._set_current(None, async_sel=False)
        self._complete_lifecycle_hook_after(
            self._transition_children(
                list(self.snapshot()),
                construct=False,
                after=super()._on_destruct,
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
            snapshot = list(self._children)
        _dispose_children_then_self(snapshot, super().dispose)

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

    def _end_membership_transaction(self) -> None:
        with self._membership_condition:
            self._membership_transaction_active = False
            self._membership_transaction_owner = None
            dispose = self._dispose_deferred
            self._dispose_deferred = False
            self._membership_condition.notify_all()
        if dispose:
            self.dispose()

    def _on_dispose(self) -> None:
        """Complete the collection_changed subject."""
        if not self._collection_changed_subject.is_disposed:
            self._collection_changed_subject.on_completed()
            self._collection_changed_subject.dispose()

    # ── Factory hook (overridden by subclasses) ───────────────────────────────

    def _populate_children(self) -> None:
        """Called once during construct() to add children from factory.

        Default: no-op (children were added manually via append/insert/etc.).
        Subclasses override to evaluate their factory.
        """

    def _attach_population(self, children: Iterable[VM]) -> None:
        """Attach one factory population as an all-or-nothing transaction."""
        candidates = list(children)
        if len({id(child) for child in candidates}) != len(candidates):
            raise ValueError("factory population contains a duplicate child identity")
        self._begin_membership_transaction()
        transfers: list[_ParentTransfer | None] = []
        original_statuses: list[ConstructionStatus] = []
        parent: _ParentCompositeVM = self
        try:
            for child in candidates:
                transfer = _begin_parent_transfer(child, parent)
                transfers.append(transfer)
                original_statuses.append(child.status)
            with self._membership_gate:
                self._require_transaction_can_continue_locked()
                for child in candidates:
                    self._children.append(child)
                    child._set_parent(parent)

            # Populate the complete snapshot before invoking any child hook,
            # but never execute user lifecycle hooks while holding the
            # destination membership gate.
            for child in candidates:
                if (
                    self.status is ConstructionStatus.CONSTRUCTING
                    and child.status is not ConstructionStatus.CONSTRUCTED
                ):
                    child.construct()
                else:
                    self._maybe_auto_construct(child)
        except BaseException as original_error:
            compensation_error: BaseException | None = None
            for child, original_status in reversed(
                list(zip(candidates, original_statuses, strict=False))
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
            for staged_transfer in transfers:
                if staged_transfer is not None:
                    staged_transfer.commit()
            for child in candidates:
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
        finally:
            self._end_membership_transaction()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_current(self, value: VM | None, *, async_sel: bool) -> None:
        """Apply the current change, optionally dispatching via foreground."""
        if async_sel:
            with self._membership_gate:
                if self._membership_transaction_active:
                    raise RuntimeError("container membership transaction is already in progress")
                if value is not None and not any(child is value for child in self._children):
                    raise ValueError(
                        f"Cannot set current to '{getattr(value, 'name', value)!r}': "
                        "not a member of this composite."
                    )
            captured = value

            def _dispatch(scheduler: SchedulerBase, state: object | None) -> None:
                self._apply_current_change(captured, strict=False)

            self._dispatcher.foreground.schedule(_dispatch)
        else:
            self._apply_current_change(value)

    def _apply_current_change(
        self,
        value: VM | None,
        *,
        internal: bool = False,
        strict: bool = True,
    ) -> None:
        """Synchronously update _current and fire notifications."""
        # Async TOCTOU guard: with async selection the child may have been removed
        # between _set_current's membership check and this deferred foreground
        # delivery. Dropping silently upholds the spec/06 §3 invariant that a
        # non-null current is always a member of the children collection.
        with self._membership_gate:
            if self._membership_transaction_active and not internal:
                if not strict:
                    return
                raise RuntimeError("container membership transaction is already in progress")
            if value is not None and not any(child is value for child in self._children):
                if not strict:
                    return
                raise ValueError(
                    f"Cannot set current to '{getattr(value, 'name', value)!r}': "
                    "not a member of this composite."
                )
            if self._current is value:
                return
            previous = self._current
            self._current = value
            self._finish_current_change(previous, value)

    def _finish_current_change(self, previous: VM | None, value: VM | None) -> None:
        """Publish one already-committed selection change under the membership gate."""

        # Update IsCurrent on affected children.
        if previous is not None:
            previous._set_is_current(False)
        if value is not None:
            value._set_is_current(True)

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
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        children_factory: Callable[[], Iterable[VM]] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
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
        hub: MessageHub[Message] | None = None,
        dispatcher: Dispatcher | None = None,
        children: Callable[[], Iterable[VM]],
        hint: str = "",
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        current: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
    ) -> CompositeVM[VM]:
        """Construct a :class:`CompositeVM` from keyword options in one call.

        An additive alternative to :meth:`builder` (ADR-0055 / VMX-020).
        Delegates to :class:`CompositeVMBuilder`, so required-field validation
        (``BuilderValidationError`` on a missing ``name``/``hub``/``dispatcher``)
        and the resulting VM are identical to the fluent path. ``children`` is a
        required keyword (pass ``lambda: ()`` for an initially empty composite).
        """
        builder: CompositeVMBuilder[VM] = CompositeVMBuilder()
        builder = (
            builder.hint(hint)
            .async_selection(async_selection)
            .auto_construct_on_add(auto_construct_on_add)
            .children(children)
        )
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
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        async_selection: bool = False,
        auto_construct_on_add: bool = False,
        children_models: Callable[[], Iterable[M]],
        child_model_to_child_vm: Callable[[M], VM],
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        current_selector: Callable[[Iterable[VM]], VM | None] | None = None,
        on_current_changed: Callable[[VM | None], None] | None = None,
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
        )
        self._children_models: Callable[[], Iterable[M]] = children_models
        self._child_model_to_child_vm: Callable[[M], VM] = child_model_to_child_vm

    @staticmethod
    def builder() -> CompositeVMOfBuilder[M, VM]:
        """Return a new immutable builder for :class:`CompositeVMOf`."""
        return CompositeVMOfBuilder()

    def _populate_children(self) -> None:
        children = [self._child_model_to_child_vm(model) for model in self._children_models()]
        self._attach_population(children)


# Deferred import to avoid circular references.
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder  # noqa: E402
