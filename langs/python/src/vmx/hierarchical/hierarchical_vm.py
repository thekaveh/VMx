"""HierarchicalVM[TModel, TVM] — first-class recursive tree ViewModel.

See spec/18-hierarchical-vm.md and ADR-0028.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
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


class MissingParentPolicy(Enum):
    """Retention policy for batch items whose parent key is not materialized."""

    PARK = "park"
    REJECT = "reject"


class BatchAttachRejectionReason(Enum):
    """Typed reason why an input item was not attached by ``attach_many``."""

    DUPLICATE_EXISTING_KEY = "duplicate_existing_key"
    DUPLICATE_BATCH_KEY = "duplicate_batch_key"
    ALREADY_ATTACHED = "already_attached"
    MISSING_PARENT = "missing_parent"
    CYCLE = "cycle"
    SELECTOR_FAILED = "selector_failed"
    ATTACHMENT_FAILED = "attachment_failed"


@dataclass(frozen=True)
class BatchAttachRejection(Generic[TVM]):
    """One non-throwing batch-attachment rejection."""

    item: TVM
    reason: BatchAttachRejectionReason
    detail: str | None = None


@dataclass(frozen=True)
class BatchAttachResult(Generic[TVM]):
    """Structured outcome of one ``attach_many`` call."""

    added: list[TVM]
    duplicates: list[TVM]
    orphans: list[TVM]
    rejections: list[BatchAttachRejection[TVM]]


@dataclass(frozen=True)
class _BatchAttachCandidate(Generic[TVM]):
    item: TVM
    key: Hashable
    parent_key: Hashable | None
    retain_if_missing: bool


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
        Message hub for pub/sub. **Required** — must be wired explicitly so a
        tree never silently fabricates an isolated hub (ADR-0052; VMX-080).
    dispatcher:
        Dispatcher for async/background scheduling. **Required** — see ``hub``.
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
        hub: MessageHub[Any],
        dispatcher: Dispatcher,
        name: str | None = None,
        hint: str = "",
        eager_children: bool = False,
    ) -> None:
        super().__init__(
            name=name or type(self).__name__,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
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
        # Missing-parent items retained by attach_many. Calls made on a
        # descendant always redirect here on the structural root.
        self._parked_attach_items: list[TVM] = []

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
            self._complete_lifecycle_hook_after(
                self._transition_children(list(self.children), construct=True)
            )

    # ── Structural mutation ──────────────────────────────────────────────────

    def add_child(self, child: TVM) -> None:
        """Add *child* to this node's children, set its parent, and publish
        :class:`~vmx.messages.TreeStructureChangedMessage`.
        """
        if child is None:
            raise ValueError("child must not be None")
        self._attach_child(child, explicit_reparent=False)

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
        self._attach_child(child, explicit_reparent=True)

    def _attach_child(self, child: TVM, *, explicit_reparent: bool) -> None:
        if child._hierarchical_parent is self:
            return  # already our child — no-op

        # HIER-018: reparenting this node or one of its ancestors under
        # itself would create a parent cycle and corrupt depth/path/walk.
        if any(node is child for node in self.path):
            raise ValueError(
                f"Cannot reparent '{child.name}' under '{self.name}': "
                "it is this node or one of its ancestors (HIER-018)."
            )

        # Materialize before mutation so factory failure cannot leave a child
        # detached from its original parent.
        self._ensure_children_materialized()
        old_parent = child._hierarchical_parent
        old_index = -1
        if old_parent is not None:
            old_parent._ensure_children_materialized()
            assert old_parent._children_list is not None
            for i, sibling in enumerate(old_parent._children_list):
                if sibling is child:
                    old_index = i
                    break

        assert self._children_list is not None
        new_index = len(self._children_list)
        if old_index >= 0:
            assert old_parent is not None and old_parent._children_list is not None
            del old_parent._children_list[old_index]
        try:
            self._children_list.append(child)
            child._set_hierarchical_parent(self)
        except BaseException:
            self._children_list[:] = [
                candidate for candidate in self._children_list if candidate is not child
            ]
            if old_index >= 0:
                assert old_parent is not None and old_parent._children_list is not None
                old_parent._children_list.insert(old_index, child)
            if child._hierarchical_parent is not old_parent:
                child._set_hierarchical_parent(old_parent)
            raise

        reparented = explicit_reparent or old_parent is not None
        self._hub.send(
            TreeStructureChangedMessage(
                sender=self,
                sender_name=self._name,
                change=(
                    TreeStructureChange.REPARENTED if reparented else TreeStructureChange.ADDED
                ),
                affected=child,
                index=-1 if reparented else new_index,
            )
        )

    @property
    def parked_attach_count(self) -> int:
        """Number of missing-parent items retained on the structural root."""
        return len(self._tree_root()._parked_attach_items)

    def attach_many(
        self,
        items: Iterable[TVM],
        *,
        key_of: Callable[[TVM], Hashable],
        parent_key_of: Callable[[TVM], Hashable | None],
        on_missing_parent: MissingParentPolicy = MissingParentPolicy.PARK,
    ) -> BatchAttachResult[TVM]:
        """Attach an out-of-order batch beneath this node's structural root.

        ``None`` from ``parent_key_of`` means a direct child of the root.
        Duplicate keys, missing parents, selector failures, cycles, and
        already-attached nodes are reported rather than raised. Only genuine
        missing-parent items are retained by the ``PARK`` policy.
        """
        root = self._tree_root()
        incoming = list(items)
        parked = list(root._parked_attach_items)
        root._parked_attach_items.clear()
        added: list[TVM] = []
        duplicates: list[TVM] = []
        orphans: list[TVM] = []
        rejections: list[BatchAttachRejection[TVM]] = []

        existing: dict[Hashable, TVM] = {}
        try:
            for node in root._materialized_subtree():
                key = key_of(node)
                self._validate_batch_key(key)
                existing.setdefault(key, node)
        except Exception as exc:  # selectors are consumer code; contain them
            root._parked_attach_items.extend(parked)
            for item in [*parked, *incoming]:
                rejections.append(
                    BatchAttachRejection(
                        item,
                        BatchAttachRejectionReason.SELECTOR_FAILED,
                        str(exc),
                    )
                )
            return BatchAttachResult(added, duplicates, orphans, rejections)

        candidates: list[_BatchAttachCandidate[TVM]] = []
        candidate_keys: set[Hashable] = set()
        for item, was_parked in [
            *((item, True) for item in parked),
            *((item, False) for item in incoming),
        ]:
            try:
                key = key_of(item)
                self._validate_batch_key(key)
                parent_key = parent_key_of(item)
                if parent_key is not None:
                    self._validate_batch_key(parent_key)
            except Exception as exc:
                if was_parked:
                    root._parked_attach_items.append(item)
                rejections.append(
                    BatchAttachRejection(
                        item,
                        BatchAttachRejectionReason.SELECTOR_FAILED,
                        str(exc),
                    )
                )
                continue

            if key in existing:
                duplicates.append(item)
                rejections.append(
                    BatchAttachRejection(
                        item,
                        BatchAttachRejectionReason.DUPLICATE_EXISTING_KEY,
                    )
                )
                continue
            if key in candidate_keys:
                duplicates.append(item)
                rejections.append(
                    BatchAttachRejection(
                        item,
                        BatchAttachRejectionReason.DUPLICATE_BATCH_KEY,
                    )
                )
                continue
            if item._hierarchical_parent is not None:
                rejections.append(
                    BatchAttachRejection(
                        item,
                        BatchAttachRejectionReason.ALREADY_ATTACHED,
                    )
                )
                continue

            candidate_keys.add(key)
            candidates.append(
                _BatchAttachCandidate(
                    item,
                    key,
                    parent_key,
                    was_parked or on_missing_parent is MissingParentPolicy.PARK,
                )
            )

        unresolved = candidates
        while unresolved:
            next_unresolved: list[_BatchAttachCandidate[TVM]] = []
            progressed = False
            for candidate in unresolved:
                parent: TVM | None
                if candidate.parent_key is None:
                    parent = root
                else:
                    parent = existing.get(candidate.parent_key)
                if parent is None:
                    next_unresolved.append(candidate)
                    continue

                try:
                    parent.add_child(candidate.item)
                except Exception as exc:
                    self._rollback_batch_attach(parent, candidate.item)
                    rejections.append(
                        BatchAttachRejection(
                            candidate.item,
                            BatchAttachRejectionReason.ATTACHMENT_FAILED,
                            str(exc),
                        )
                    )
                    continue

                existing[candidate.key] = candidate.item
                added.append(candidate.item)
                progressed = True
            unresolved = next_unresolved
            if not progressed:
                break

        unresolved_by_key = {candidate.key: candidate for candidate in unresolved}
        for candidate in unresolved:
            is_cycle = self._batch_parent_chain_cycles(candidate, unresolved_by_key)
            reason = (
                BatchAttachRejectionReason.CYCLE
                if is_cycle
                else BatchAttachRejectionReason.MISSING_PARENT
            )
            rejections.append(BatchAttachRejection(candidate.item, reason))
            if not is_cycle:
                orphans.append(candidate.item)
                if candidate.retain_if_missing:
                    root._parked_attach_items.append(candidate.item)

        return BatchAttachResult(added, duplicates, orphans, rejections)

    def invalidate_children(self) -> None:
        """Drop this node's materialized child cache.

        The next :attr:`children` access invokes ``children_factory`` again.
        Invalidating an unmaterialized node is a no-op.
        """
        if self._children_list is None:
            return
        for child in self._children_list:
            if child._hierarchical_parent is self:
                child._hierarchical_parent = None
                child._path_cache = None
                child._invalidate_path_cache_descendants()
        self._children_list = None
        self._children_view = None
        self._hub.send(
            PropertyChangedMessage.create(
                sender=self,
                sender_name=self._name,
                property_name="children",
            )
        )

    def invalidate_subtree(self) -> None:
        """Drop cached children for this node and all materialized descendants."""
        if self._children_list is None:
            return
        for child in list(self._children_list):
            child.invalidate_subtree()
        self.invalidate_children()

    def _on_dispose(self) -> None:
        self._parked_attach_items.clear()
        super()._on_dispose()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _materialize_children(self) -> list[TVM]:
        children = list(self._children_factory(self))  # type: ignore[arg-type]
        for child in children:
            child._hierarchical_parent = self
        return children

    def _tree_root(self) -> TVM:
        node: TVM = self  # type: ignore[assignment]  # CRTP self view
        while node._hierarchical_parent is not None:
            node = node._hierarchical_parent
        return node

    def _materialized_subtree(self) -> Iterator[TVM]:
        stack: list[TVM] = [self]  # type: ignore[list-item]
        while stack:
            node = stack.pop()
            yield node
            cached = node._children_list
            if cached is not None:
                stack.extend(reversed(cached))

    @staticmethod
    def _validate_batch_key(key: Hashable) -> None:
        if key is None:
            raise ValueError("key_of must not return None")
        hash(key)

    @staticmethod
    def _batch_parent_chain_cycles(
        candidate: _BatchAttachCandidate[TVM],
        unresolved: dict[Hashable, _BatchAttachCandidate[TVM]],
    ) -> bool:
        seen: set[Hashable] = set()
        current: _BatchAttachCandidate[TVM] | None = candidate
        while current is not None:
            if current.key in seen:
                return True
            seen.add(current.key)
            if current.parent_key is None:
                return False
            current = unresolved.get(current.parent_key)
        return False

    @staticmethod
    def _rollback_batch_attach(parent: TVM, child: TVM) -> None:
        if parent._children_list is not None:
            parent._children_list[:] = [item for item in parent._children_list if item is not child]
        child._hierarchical_parent = None
        child._path_cache = None
        child._invalidate_path_cache_descendants()

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
