"""GroupVM — ordered peer-child container with no selection slot.

GroupVM<VM> is a container of peers: an ordered list of child VMs with no
``current`` selection and no child-navigation commands. It is identical to
CompositeVM minus the Current slot and minus selection-related members.

Children ARE constructed/destructed in concert (parallel within synchronous
execution), matching CompositeVM's orchestration contract.

See spec/07-group-vm.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Generic, TypeVar

from reactivex.subject import Subject

from vmx.collections import BatchUpdateHandle, CollectionChangedEvent
from vmx.components.base import _ComponentVMBase, _ParentCompositeVM
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

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
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        auto_construct_on_add: bool = False,
        children_factory: Callable[[], Iterable[VM]] | None = None,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
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
        self._children: list[VM] = []
        self._children_factory: Callable[[], Iterable[VM]] | None = children_factory
        self._populated: bool = False
        self._batch_depth: int = 0
        self._batch_dirty: bool = False

        # Observable collection-change stream.
        self._collection_changed_subject: Subject[CollectionChangedEvent] = Subject()

    # ── ViewModelType ────────────────────────────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.GROUP

    # ── Collection-change observable ─────────────────────────────────────────

    @property
    def on_collection_changed(self) -> Subject[CollectionChangedEvent]:
        """Observable that emits :class:`CollectionChangedEvent` on structural changes."""
        return self._collection_changed_subject

    # ── MutableSequence-like interface ───────────────────────────────────────

    def __len__(self) -> int:
        return len(self._children)

    def __iter__(self) -> Iterator[VM]:
        return iter(self._children)

    def __contains__(self, item: object) -> bool:
        return item in self._children

    def __getitem__(self, index: int) -> VM:
        return self._children[index]

    def __setitem__(self, index: int, value: VM) -> None:
        old = self._children[index]
        self._children[index] = value
        old._set_parent(None)
        value._set_parent(self._as_parent())
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(old,), old_index=index)
        )
        self._maybe_auto_construct(value)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(value,), new_index=index)
        )

    def __delitem__(self, index: int) -> None:
        self.remove_at(index)

    def index_of(self, item: VM) -> int:
        """Return the index of *item*, or ``-1`` if not found."""
        try:
            return self._children.index(item)
        except ValueError:
            return -1

    def insert(self, index: int, item: VM) -> None:
        """Insert *item* at *index*, shifting existing children right."""
        self._children.insert(index, item)
        item._set_parent(self._as_parent())
        self._maybe_auto_construct(item)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(item,), new_index=index)
        )

    def add(self, item: VM) -> None:
        """Append *item* to the end of the children list."""
        idx = len(self._children)
        self._children.append(item)
        item._set_parent(self._as_parent())
        self._maybe_auto_construct(item)
        self._emit_collection_changed(
            CollectionChangedEvent(action="add", new_items=(item,), new_index=idx)
        )

    # Alias: append mirrors Python list convention.
    append = add

    def remove(self, item: VM) -> bool:
        """Remove first occurrence of *item*. Returns True if removed."""
        idx = self.index_of(item)
        if idx < 0:
            return False
        self.remove_at(idx)
        return True

    def remove_at(self, index: int) -> None:
        """Remove the child at *index*."""
        item = self._children[index]
        del self._children[index]
        item._set_parent(None)
        self._emit_collection_changed(
            CollectionChangedEvent(action="remove", old_items=(item,), old_index=index)
        )

    def clear(self) -> None:
        """Remove all children."""
        for child in self._children:
            child._set_parent(None)
        self._children.clear()
        self._emit_collection_changed(CollectionChangedEvent(action="reset"))

    # ── Batch + auto-construct (spec v1.1) ──────────────────────────────────

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

    # ── Lifecycle overrides ──────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate from factory (once) then construct every child."""
        # Invoke the builder's on_construct callback first.
        if self._on_construct_cb is not None:
            self._on_construct_cb()
        self._populate_children()
        # Snapshot (parity with _CompositeVMBase and dispose below): a child
        # lifecycle hook that mutates the group must not skip/repeat siblings.
        for child in list(self._children):
            child.construct()

    def _on_destruct(self) -> None:
        """Destruct every child, then invoke the builder's on_destruct callback."""
        for child in list(self._children):
            child.destruct()
        if self._on_destruct_cb is not None:
            self._on_destruct_cb()

    def dispose(self) -> None:
        """Dispose cascade (LIFE-013): depth-first dispose each child, then self."""
        for child in list(self._children):
            child.dispose()
        super().dispose()

    def _on_dispose(self) -> None:
        if not self._collection_changed_subject.is_disposed:
            self._collection_changed_subject.on_completed()
            self._collection_changed_subject.dispose()

    def _populate_children(self) -> None:
        """Evaluate the children factory (idempotent: runs at most once)."""
        if self._populated or self._children_factory is None:
            return
        self._populated = True
        for child in self._children_factory():
            self.add(child)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _as_parent(self) -> _GroupParent[VM]:
        """Return a _ParentCompositeVM adaptor for child.set_parent() calls."""
        return _GroupParent(self)

    # ── count property alias ─────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of children (alias for ``len(group)``)."""
        return len(self._children)


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
    def current_child(self) -> object | None:
        return None

    def select_child(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM has no selection concept."""

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM has no selection concept."""
