"""CompositeVM (non-modeled) and CompositeVMOf[M, VM] (modeled composite).

See spec/06-composite-vm.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex.abc import SchedulerBase
from reactivex.subject import Subject

from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.components.base import _ComponentVMBase, _ParentCompositeVM
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
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
        self._current_selector: Callable[[Iterable[VM]], VM | None] | None = current_selector

    # ── ViewModelType ─────────────────────────────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPOSITE

    # ── IParentCompositeVM implementation ─────────────────────────────────────

    @property
    def current_child(self) -> object | None:
        return self._current

    def select_child(self, vm: _ComponentVMBase) -> None:
        if isinstance(vm, _ComponentVMBase):
            # Use typed access via _set_current
            for child in self._children:
                if child is vm:
                    self._set_current(child, async_sel=self._async_selection)
                    return

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        if self._current is vm:
            self._set_current(None, async_sel=self._async_selection)

    # ── on_collection_changed ─────────────────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedEvent]:
        """Observable that emits a CollectionChangedEvent on every mutation."""
        return self._collection_changed_subject

    # ── current property ─────────────────────────────────────────────────────

    @property
    def current(self) -> VM | None:
        """The currently selected child, or None."""
        return self._current

    @current.setter
    def current(self, value: VM | None) -> None:
        """Set current selection.

        - None is always legal.
        - Non-None must be in children; raises ValueError otherwise.
        - If async_selection is True, dispatches via foreground scheduler.
        """
        if value is not None and value not in self._children:
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
        if self._current is not vm:
            raise ValueError(
                f"Cannot deselect '{getattr(vm, 'name', vm)!r}': it is not the current selection."
            )
        self.current = None

    def can_select_component(self, vm: VM) -> bool:
        """Return True iff *vm* is in children and Status == Constructed."""
        return vm in self._children and vm.status == ConstructionStatus.CONSTRUCTED

    # ── MutableSequence-like collection API ───────────────────────────────────

    @property
    def count(self) -> int:
        """Number of children."""
        return len(self._children)

    def __len__(self) -> int:
        return len(self._children)

    def __iter__(self) -> Iterator[VM]:
        return iter(self._children)

    def __contains__(self, item: object) -> bool:
        return item in self._children

    @overload
    def __getitem__(self, index: int) -> VM: ...

    @overload
    def __getitem__(self, index: slice) -> list[VM]: ...

    def __getitem__(self, index: int | slice) -> VM | list[VM]:
        if isinstance(index, slice):
            return self._children[index]
        return self._children[index]

    def __setitem__(self, index: int, value: VM) -> None:
        old = self._children[index]
        self._children[index] = value
        old._set_parent(None)
        # Mirror _remove_at: if the slot we just replaced held the current
        # selection, drop Current to None before subscribers see any
        # collection_changed event for this replace.
        if self._current is old:
            self._set_current(None, async_sel=False)
        value._set_parent(self)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(old,), old_index=index)
        )
        self._maybe_auto_construct(value)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(value,), new_index=index)
        )

    def __delitem__(self, index: int) -> None:
        self._remove_at(index)

    def index(self, value: VM, start: int = 0, stop: int | None = None) -> int:
        """Return the index of *value* in children."""
        if stop is None:
            return self._children.index(value, start)
        return self._children.index(value, start, stop)

    def insert(self, index: int, item: VM) -> None:
        """Insert *item* before *index*, emitting a collection-changed event
        whose ``new_index`` is the actual insertion position (stdlib
        semantics: negatives count from the end, out-of-range clamps).
        """
        if index < 0:
            index = max(index + len(self._children), 0)
        elif index > len(self._children):
            index = len(self._children)
        self._children.insert(index, item)
        item._set_parent(self)
        self._maybe_auto_construct(item)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(item,), new_index=index)
        )

    def append(self, item: VM) -> None:
        """Append *item*, emitting a collection-changed event."""
        self._children.append(item)
        item._set_parent(self)
        idx = len(self._children) - 1
        self._maybe_auto_construct(item)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(item,), new_index=idx)
        )

    def add(self, item: VM) -> None:
        """Alias for ``append``."""
        self.append(item)

    def remove(self, item: VM) -> bool:
        """Remove first occurrence of *item*.  Returns True on success."""
        try:
            idx = self._children.index(item)
        except ValueError:
            return False
        self._remove_at(idx)
        return True

    def remove_at(self, index: int) -> None:
        """Remove child at *index*."""
        self._remove_at(index)

    def clear(self) -> None:
        """Remove all children, emitting a Reset event."""
        for child in self._children:
            child._set_parent(None)
        self._children.clear()
        # Route through _set_current (mirrors C# Clear / _remove_at): a bare
        # `self._current = None` left the old current child's is_current True
        # and skipped the "current" property notification.
        self._set_current(None, async_sel=False)
        self._emit_collection_changed(CollectionChangedEvent(action="reset"))

    def copy_to(self, target: list[VM], array_index: int) -> None:
        """Copy children into *target* starting at *array_index*."""
        for i, child in enumerate(self._children):
            target[array_index + i] = child

    def _remove_at(self, index: int) -> None:
        item = self._children[index]
        del self._children[index]
        item._set_parent(None)
        if self._current is item:
            self._set_current(None, async_sel=False)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(item,), old_index=index)
        )

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
        if self._batch_depth == 0 and self._batch_dirty:
            self._batch_dirty = False
            self._collection_changed_subject.on_next(CollectionChangedEvent(action="reset"))

    def _emit_collection_changed(self, event: CollectionChangedEvent) -> None:
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

    # ── Lifecycle overrides ───────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate children (once) then call construct() on each.

        After all children reach Constructed, apply the optional initial-current
        selector (spec/06 §3.X, ADR-0042). The composite is still in Constructing
        here; every child is Constructed. A selector returning None or an
        out-of-set value leaves current at its prior value (initially None) and
        emits no notification — matching the select_component semantics.
        """
        super()._on_construct()
        if not self._populated:
            self._populated = True
            self._populate_children()
        # Construct all children.
        for child in list(self._children):
            child.construct()
        # Apply the optional initial-current selector.
        if self._current_selector is not None:
            initial = self._current_selector(self)
            if initial is not None and initial in self._children:
                self._set_current(initial, async_sel=False)

    def _on_destruct(self) -> None:
        """Set current=None then destruct all children."""
        if self._current is not None:
            self._set_current(None, async_sel=False)
        for child in list(self._children):
            child.destruct()
        super()._on_destruct()

    def dispose(self) -> None:
        """Dispose cascade (LIFE-013): depth-first dispose each child, then self."""
        for child in list(self._children):
            child.dispose()
        super().dispose()

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

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_current(self, value: VM | None, *, async_sel: bool) -> None:
        """Apply the current change, optionally dispatching via foreground."""
        if value is not None and value not in self._children:
            raise ValueError(
                f"Cannot set current to '{getattr(value, 'name', value)!r}': "
                "not a member of this composite."
            )
        if async_sel:
            captured = value

            def _dispatch(scheduler: SchedulerBase, state: object | None) -> None:
                self._apply_current_change(captured)

            self._dispatcher.foreground.schedule(_dispatch)
        else:
            self._apply_current_change(value)

    def _apply_current_change(self, value: VM | None) -> None:
        """Synchronously update _current and fire notifications."""
        if self._current is value:
            return

        previous = self._current
        self._current = value

        # Update IsCurrent on affected children.
        if previous is not None:
            previous._set_is_current(False)
        if value is not None:
            value._set_is_current(True)

        # Emit PropertyChangedMessage("current") on the hub.
        self._hub.send(PropertyChangedMessage.create(self, self._name, "current"))
        self._raise_property_changed("current")


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
        )
        self._children_factory: Callable[[], Iterable[VM]] | None = children_factory

    @staticmethod
    def builder() -> CompositeVMBuilder[VM]:
        """Return a new immutable builder for :class:`CompositeVM`."""
        return CompositeVMBuilder()

    def _populate_children(self) -> None:
        if self._children_factory is None:
            return
        for child in self._children_factory():
            self.append(child)


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
        )
        self._children_models: Callable[[], Iterable[M]] = children_models
        self._child_model_to_child_vm: Callable[[M], VM] = child_model_to_child_vm

    @staticmethod
    def builder() -> CompositeVMOfBuilder[M, VM]:
        """Return a new immutable builder for :class:`CompositeVMOf`."""
        return CompositeVMOfBuilder()

    def _populate_children(self) -> None:
        for model in self._children_models():
            child = self._child_model_to_child_vm(model)
            self.append(child)


# Deferred import to avoid circular references.
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder  # noqa: E402
