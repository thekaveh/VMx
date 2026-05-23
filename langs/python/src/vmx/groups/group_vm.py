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

from vmx.components.base import _ComponentVMBase, _ParentCompositeVM
from vmx.components.protocols import ViewModelType
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

VM = TypeVar("VM", bound=_ComponentVMBase)


# ---------------------------------------------------------------------------
# CollectionChangedEvent — lightweight equivalent of NotifyCollectionChanged
# ---------------------------------------------------------------------------


class CollectionChangedEvent:
    """Carries a single collection-change notification.

    Mirrors the ``NotifyCollectionChangedEventArgs`` shape used in the C# spec
    but uses Python-friendly snake_case attributes.

    Attributes
    ----------
    action:
        ``"add"`` or ``"remove"`` or ``"reset"``.
    new_items:
        List of items added (empty for remove / reset).
    removed_items:
        List of items removed (empty for add / reset).
    new_index:
        Index at which items were added (``-1`` for remove/reset).
    removed_index:
        Index from which items were removed (``-1`` for add/reset).
    """

    __slots__ = ("action", "new_index", "new_items", "removed_index", "removed_items")

    def __init__(
        self,
        action: str,
        new_items: list[object] | None = None,
        removed_items: list[object] | None = None,
        new_index: int = -1,
        removed_index: int = -1,
    ) -> None:
        self.action: str = action
        self.new_items: list[object] = new_items if new_items is not None else []
        self.removed_items: list[object] = removed_items if removed_items is not None else []
        self.new_index: int = new_index
        self.removed_index: int = removed_index

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CollectionChangedEvent(action={self.action!r}, "
            f"new_items={self.new_items!r}, new_index={self.new_index})"
        )


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
      inherited from the IComponentVM baseline in ``_ComponentVMBase``).
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
        self._children: list[VM] = []
        self._children_factory: Callable[[], Iterable[VM]] | None = children_factory
        self._populated: bool = False

        # Observable collection-change stream.
        self._collection_changed_subject: Subject[CollectionChangedEvent] = Subject()

    # ── ViewModelType ────────────────────────────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.GROUP

    # ── IParentCompositeVM (no-op: GroupVM has no selection) ─────────────────
    # Children may try to select/deselect themselves; these are safe no-ops.

    @property
    def _current_child(self) -> object | None:
        """GroupVM has no selection slot — always returns None."""
        return None

    def _select_child_impl(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM children are peers — no selection concept."""

    def _deselect_child_impl(self, vm: _ComponentVMBase) -> None:
        """No-op: GroupVM children are peers — no selection concept."""

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
        # Notify as Remove then Add (standard collection-change pattern).
        self._collection_changed_subject.on_next(
            CollectionChangedEvent(
                action="remove",
                removed_items=[old],
                removed_index=index,
            )
        )
        self._collection_changed_subject.on_next(
            CollectionChangedEvent(
                action="add",
                new_items=[value],
                new_index=index,
            )
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
        self._collection_changed_subject.on_next(
            CollectionChangedEvent(
                action="add",
                new_items=[item],
                new_index=index,
            )
        )

    def add(self, item: VM) -> None:
        """Append *item* to the end of the children list."""
        idx = len(self._children)
        self._children.append(item)
        item._set_parent(self._as_parent())
        self._collection_changed_subject.on_next(
            CollectionChangedEvent(
                action="add",
                new_items=[item],
                new_index=idx,
            )
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
        self._collection_changed_subject.on_next(
            CollectionChangedEvent(
                action="remove",
                removed_items=[item],
                removed_index=index,
            )
        )

    def clear(self) -> None:
        """Remove all children."""
        for child in self._children:
            child._set_parent(None)
        self._children.clear()
        self._collection_changed_subject.on_next(CollectionChangedEvent(action="reset"))

    # ── Lifecycle overrides ──────────────────────────────────────────────────

    def _on_construct(self) -> None:
        """Populate from factory (once) then construct every child."""
        # Invoke the builder's on_construct callback first.
        if self._on_construct_cb is not None:
            self._on_construct_cb()
        self._populate_children()
        for child in self._children:
            child.construct()

    def _on_destruct(self) -> None:
        """Destruct every child, then invoke the builder's on_destruct callback."""
        for child in self._children:
            child.destruct()
        if self._on_destruct_cb is not None:
            self._on_destruct_cb()

    def _on_dispose(self) -> None:
        """Cascade dispose depth-first: each child before self (LIFE-013)."""
        for child in self._children:
            child.dispose()
        # Complete the collection-changed subject.
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
