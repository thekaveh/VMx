"""HierarchicalVM[TModel, TVM] — first-class recursive tree ViewModel.

See spec/18-hierarchical-vm.md and ADR-0028.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Generic, TypeVar, overload

from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.tree_structure_changed import TreeStructureChange, TreeStructureChangedMessage
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

TModel = TypeVar("TModel")
TVM = TypeVar("TVM", bound="HierarchicalVM[Any, Any]")
_T = TypeVar("_T")


class _ReadOnlyList(Sequence[_T]):
    """Immutable, list-comparable read-only view over a backing list.

    Reads through to the live backing list but exposes no mutators, so a
    consumer handed a node's ``children``/``path`` cannot mutate it and corrupt
    the identity-cache invariants (HIER-004) or other descendants' paths
    (VMX-078). Compares equal to any list/tuple with the same elements so
    existing ``== [...]`` assertions keep working, and is intentionally
    unhashable (mirroring the ``list`` it replaces).
    """

    __slots__ = ("_backing",)

    def __init__(self, backing: list[_T]) -> None:
        self._backing = backing

    @overload
    def __getitem__(self, index: int) -> _T: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[_T]: ...

    def __getitem__(self, index: int | slice) -> _T | Sequence[_T]:
        return self._backing[index]

    def __len__(self) -> int:
        return len(self._backing)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _ReadOnlyList):
            return bool(self._backing == other._backing)
        if isinstance(other, list | tuple):
            return bool(list(self._backing) == list(other))
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]  # unhashable, like the list it wraps

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._backing!r})"


class HierarchicalVM(Generic[TModel, TVM], _ComponentVMBase):
    """Abstract recursive tree ViewModel.

    Each node carries a typed ``TModel`` and may contain children of the same
    concrete type ``TVM``.

    Children are **lazy by default**: the ``children_factory`` is not invoked
    until :attr:`children` is first accessed. Eager materialization is
    requested by passing ``eager_children=True`` at construction time, which
    causes the full subtree to be materialized and each child constructed
    during :meth:`_on_construct`, in depth-first order.

    Parameters
    ----------
    model:
        Domain model for this node.
    children_factory:
        Callable invoked with ``self`` to produce child ``TVM`` instances.
        Called lazily on first access to :attr:`children` unless
        ``eager_children=True``.
    hub:
        Message hub for pub/sub.
    dispatcher:
        Dispatcher for async/background scheduling.
    name:
        Optional VM name (defaults to the concrete class name).
    hint:
        Optional display hint string.
    eager_children:
        When ``True``, materializes the entire subtree at :meth:`construct`
        time (depth-first). Default is ``False`` (lazy).
    """

    def __init__(
        self,
        model: TModel,
        children_factory: Callable[[TVM], Iterable[TVM]],
        hub: MessageHub[Any] | None = None,
        dispatcher: Dispatcher | None = None,
        name: str | None = None,
        hint: str = "",
        eager_children: bool = False,
    ) -> None:
        from vmx.services.dispatcher import RxDispatcher

        _hub: MessageHub[Any] = hub if hub is not None else MessageHub()
        _dispatcher: Dispatcher = dispatcher if dispatcher is not None else RxDispatcher.immediate()

        super().__init__(
            name=name or type(self).__name__,
            hint=hint,
            hub=_hub,
            dispatcher=_dispatcher,
        )
        self._model: TModel = model
        self._children_factory: Callable[[TVM], Iterable[TVM]] = children_factory
        self._eager_children: bool = eager_children

        self._hierarchical_parent: TVM | None = None
        self._children_list: list[TVM] | None = None
        # Cached read-only facade over ``_children_list`` (VMX-078). The view
        # reads through to the live list (mutated in place by add/remove/
        # reparent) and is identity-stable across accesses.
        self._children_view: _ReadOnlyList[TVM] | None = None
        self._path_cache: _ReadOnlyList[TVM] | None = None

    # ── Abstract requirement (ViewModelType) ─────────────────────────────────

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    # ── Model ────────────────────────────────────────────────────────────────

    @property
    def model(self) -> TModel:
        """The domain model carried by this tree node."""
        return self._model

    # ── Tree identity predicates ─────────────────────────────────────────────

    @property
    def parent(self) -> TVM | None:
        """The parent node; ``None`` when this node is the root."""
        return self._hierarchical_parent

    @property
    def is_root(self) -> bool:
        """``True`` when :attr:`parent` is ``None``."""
        return self._hierarchical_parent is None

    @property
    def depth(self) -> int:
        """Distance from the root. Root is 0; child of root is 1; etc."""
        return 0 if self._hierarchical_parent is None else self._hierarchical_parent.depth + 1

    @property
    def is_leaf(self) -> bool:
        """``True`` when this node has no children (materializes :attr:`children`)."""
        return len(self.children) == 0

    @property
    def is_first(self) -> bool:
        """``True`` when this is the first child in its parent's list."""
        if self._hierarchical_parent is None:
            return False
        sibs = self._hierarchical_parent.children
        return len(sibs) > 0 and sibs[0] is self

    @property
    def is_last(self) -> bool:
        """``True`` when this is the last child in its parent's list."""
        if self._hierarchical_parent is None:
            return False
        sibs = self._hierarchical_parent.children
        return len(sibs) > 0 and sibs[-1] is self

    # ── Children ─────────────────────────────────────────────────────────────

    @property
    def children(self) -> Sequence[TVM]:
        """The ordered, read-only sequence of child nodes (lazily materialized).

        Spec (chapter 18 §2) mandates ``IReadOnlyList<TVM>``; Python returns a
        genuinely read-only view (``_ReadOnlyList``) over the cached list, so a
        caller cannot mutate it and corrupt the HIER-004 identity cache
        (VMX-078). The view reads through to the live list and is identity-stable
        across accesses.
        """
        if self._children_list is None:
            self._children_list = self._materialize_children()
        if self._children_view is None:
            self._children_view = _ReadOnlyList(self._children_list)
        return self._children_view

    # ── Path ─────────────────────────────────────────────────────────────────

    @property
    def path(self) -> Sequence[TVM]:
        """Materialized, cached read-only path from the root to this node (inclusive).

        The cache is invalidated when :attr:`parent` changes. The returned value
        is a genuinely read-only view (``_ReadOnlyList``) — HIER-004 asserts
        cached-identity (``grandchild.path is path``) and a mutable return would
        let a caller corrupt the cache (VMX-078).
        """
        if self._path_cache is None:
            self._path_cache = _ReadOnlyList(self._build_path())
        return self._path_cache

    # ── __iter__ — supports walk / walk_expanded ─────────────────────────────

    def __iter__(self) -> Iterator[TVM]:
        """Iterate materialized children — enables ``walk`` / ``walk_expanded``."""
        return iter(self.children)

    # ── Lifecycle override — eager construction ───────────────────────────────

    def _on_construct(self) -> None:
        super()._on_construct()
        if self._eager_children:
            # Depth-first: materialize and construct children before returning.
            for child in self.children:
                child.construct()

    # ── Structural mutation ──────────────────────────────────────────────────

    def add_child(self, child: TVM) -> None:
        """Add *child* to this node's children, set its parent, and publish
        :class:`~vmx.messages.TreeStructureChangedMessage`.
        """
        if child is None:
            raise ValueError("child must not be None")
        self._ensure_children_materialized()
        index = len(self._children_list)  # type: ignore[arg-type]
        self._children_list.append(child)  # type: ignore[union-attr]
        child._set_hierarchical_parent(self)
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=TreeStructureChange.ADDED,
                affected=child,
                index=index,
            )
        )

    def remove_child(self, child: TVM) -> None:
        """Remove *child* from this node's children and publish
        :class:`~vmx.messages.TreeStructureChangedMessage`.
        """
        if child is None:
            raise ValueError("child must not be None")
        self._ensure_children_materialized()
        assert self._children_list is not None
        # Match by identity (not value equality) so a TVM overriding __eq__
        # cannot cause the wrong sibling to be removed — consistent with the
        # HIER-018 cycle check and the reparent detach.
        index = next(
            (i for i, sibling in enumerate(self._children_list) if sibling is child),
            -1,
        )
        if index < 0:
            return  # not a child — no-op
        self._children_list.pop(index)
        child._set_hierarchical_parent(None)
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=TreeStructureChange.REMOVED,
                affected=child,
                index=index,
            )
        )

    def reparent_child(self, child: TVM) -> None:
        """Move *child* from its current parent to this node and publish a
        REPARENTED :class:`~vmx.messages.TreeStructureChangedMessage`.
        """
        if child is None:
            raise ValueError("child must not be None")
        if child._hierarchical_parent is self:
            return  # already our child — no-op

        # HIER-018: reparenting this node or one of its ancestors under
        # itself would create a parent cycle and corrupt depth/path/walk.
        if any(node is child for node in self.path):
            raise ValueError(
                f"Cannot reparent '{child.name}' under '{self.name}': "
                "it is this node or one of its ancestors (HIER-018)."
            )

        # Detach from old parent silently. Detach by identity (not value
        # equality) to match the HIER-018 cycle check and the TS flavor: a TVM
        # overriding __eq__ must not cause the wrong sibling to be removed.
        old_parent = child._hierarchical_parent
        if old_parent is not None:
            old_parent._ensure_children_materialized()
            assert old_parent._children_list is not None
            for i, sibling in enumerate(old_parent._children_list):
                if sibling is child:
                    del old_parent._children_list[i]
                    break

        # Attach to new parent.
        self._ensure_children_materialized()
        self._children_list.append(child)  # type: ignore[union-attr]
        child._set_hierarchical_parent(self)
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=TreeStructureChange.REPARENTED,
                affected=child,
                index=-1,
            )
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _materialize_children(self) -> list[TVM]:
        children = list(self._children_factory(self))  # type: ignore[arg-type]
        for child in children:
            child._hierarchical_parent = self
        return children

    def _ensure_children_materialized(self) -> None:
        if self._children_list is None:
            self._children_list = self._materialize_children()

    def _build_path(self) -> list[TVM]:
        chain: list[Any] = []
        node: Any = self
        while node is not None:
            chain.append(node)
            node = node._hierarchical_parent
        chain.reverse()
        return chain

    def _set_hierarchical_parent(self, parent: TVM | None) -> None:
        if self._hierarchical_parent is parent:
            return
        self._hierarchical_parent = parent
        self._path_cache = None  # Invalidate path cache.
        self._invalidate_path_cache_descendants()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "parent"))

    def _invalidate_path_cache_descendants(self) -> None:
        if self._children_list is None:
            return
        for child in self._children_list:
            child._path_cache = None
            child._invalidate_path_cache_descendants()
