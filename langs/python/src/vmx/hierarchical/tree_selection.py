"""TreeSelection[TVM] — opt-in single-node selection over a HierarchicalVM tree.

See spec/18-hierarchical-vm.md §10 and ADR-0164.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from reactivex import Observable
from reactivex import operators as ops
from reactivex.abc import DisposableBase
from reactivex.subject import Subject

from vmx._disposal import _run_disposal_steps
from vmx.hierarchical.hierarchical_vm import HierarchicalVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHubProto

TVM = TypeVar("TVM", bound="HierarchicalVM[Any, Any]")


class TreeSelection(Generic[TVM]):
    """Holds one current node of the materialized tree under a root node.

    A tree node cannot be the ``current`` item of a container, so a VM that
    needs one current node per tree composes this helper on the tree's root
    (spec/18 §10). The helper adds no ``HierarchicalVM`` member and never
    navigates: :meth:`select` and :meth:`clear` do not materialize, expand,
    construct, move or dispose a node, do not change ``is_current``, and
    publish nothing to a message hub.

    While a node is current, the helper subscribes to the hub of every node
    on the path from that node to the root (one subscription per distinct
    hub). Every message whose sender is a node on that path repeats the
    :meth:`can_select` check. When the check fails, ``current`` becomes
    ``None``; when it passes, the helper watches the new path, so a move
    inside the tree keeps the selection.

    The owning VM forwards :attr:`current_changed` to its own property-change
    notification (spec/14 rule 6) and disposes the helper with itself.

    Like the tree it watches, the helper is used from one thread and takes
    no locks.

    Raises:
        ValueError: When ``root`` is ``None``.
    """

    def __init__(self, root: TVM) -> None:
        if root is None:
            raise ValueError("root must not be None")
        self._root: TVM = root
        self._current: TVM | None = None
        self._disposed = False
        self._changes: Subject[TVM | None] = Subject()
        # Changes waiting for delivery. A subscriber that selects or clears
        # re-entrantly queues its change behind the one being delivered, so
        # every subscriber observes the changes in order (spec/18 §10.3).
        self._pending: deque[TVM | None] = deque()
        self._emitting = False
        # Identities of the watched path, current node to root inclusive.
        self._watched_path: tuple[TVM, ...] = ()
        self._watched_ids: frozenset[int] = frozenset()
        # One hub subscription per distinct hub on the watched path, keyed by
        # hub identity. The hub is kept alive with its subscription.
        self._subscriptions: dict[int, tuple[MessageHubProto[Any], DisposableBase]] = {}

    @property
    def current(self) -> TVM | None:
        """The selected node, or ``None`` when nothing is selected."""
        return self._current

    @property
    def current_changed(self) -> Observable[TVM | None]:
        """Hot stream of the new :attr:`current` value, ``None`` included.

        Emits once for every effective change and replays nothing to a new
        subscriber. Completes without a value when the helper is disposed.
        """
        return self._changes.pipe(ops.as_observable())

    def can_select(self, node: TVM | None) -> bool:
        """Return whether *node* is a member of the root's materialized tree.

        True when the helper is not disposed, walking ``parent`` links from
        *node* reaches the root (the root itself qualifies), and no node on
        that path is disposed. The walk reads only ``parent`` and ``status``,
        so it never invokes a children factory (spec/18 §10.1).
        """
        if self._disposed or node is None:
            return False
        return self._path_to_root(node) is not None

    def select(self, node: TVM) -> None:
        """Make *node* current.

        Selecting the current node again does nothing. After :meth:`dispose`
        the call does nothing and raises nothing.

        Raises:
            ValueError: When *node* is ``None`` or :meth:`can_select` rejects
                it. ``current`` keeps its value and nothing is emitted.
        """
        if self._disposed:
            return
        if node is None:
            raise ValueError("node must not be None")
        path = self._path_to_root(node)
        if path is None:
            raise ValueError(
                "node is not a member of the selection root's materialized tree (spec/18 §10.1)"
            )
        if node is self._current:
            return
        self._current = node
        self._watch(path)
        self._emit(node)

    def clear(self) -> None:
        """Set :attr:`current` to ``None``.

        Does nothing when nothing is selected or after :meth:`dispose`.
        """
        if self._disposed or self._current is None:
            return
        self._current = None
        self._release_watch()
        self._emit(None)

    def dispose(self) -> None:
        """Release the hub subscriptions and complete :attr:`current_changed`.

        Sets :attr:`current` to ``None`` without emitting. Runs every step and
        re-raises the first failure. Never disposes or detaches a node.
        Idempotent.
        """
        if self._disposed:
            return
        self._disposed = True
        self._current = None
        self._pending.clear()
        subscriptions = [subscription for _, subscription in self._subscriptions.values()]
        self._subscriptions = {}
        self._watched_path = ()
        self._watched_ids = frozenset()
        _run_disposal_steps(
            *(subscription.dispose for subscription in subscriptions),
            self._changes.on_completed,
            self._changes.dispose,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _path_to_root(self, node: TVM) -> tuple[TVM, ...] | None:
        """Return the live path from *node* to the root, or ``None``."""
        path: list[TVM] = []
        cursor: TVM | None = node
        while cursor is not None:
            if cursor.status is ConstructionStatus.DISPOSED:
                return None
            path.append(cursor)
            if cursor is self._root:
                return tuple(path)
            cursor = cursor.parent
        return None

    def _watch(self, path: tuple[TVM, ...]) -> None:
        """Watch the hubs of *path*, keeping subscriptions that still apply."""
        if len(path) == len(self._watched_path) and all(
            new is old for new, old in zip(path, self._watched_path, strict=True)
        ):
            return
        self._watched_path = path
        self._watched_ids = frozenset(id(node) for node in path)
        hubs: dict[int, MessageHubProto[Any]] = {}
        for node in path:
            hubs.setdefault(id(node.hub), node.hub)
        for key in [key for key in self._subscriptions if key not in hubs]:
            _, subscription = self._subscriptions.pop(key)
            subscription.dispose()
        for key, hub in hubs.items():
            if key not in self._subscriptions:
                subscription = hub.messages.subscribe(on_next=self._handler_for(key))
                self._subscriptions[key] = (hub, subscription)

    def _release_watch(self) -> None:
        subscriptions = [subscription for _, subscription in self._subscriptions.values()]
        self._subscriptions = {}
        self._watched_path = ()
        self._watched_ids = frozenset()
        _run_disposal_steps(*(subscription.dispose for subscription in subscriptions))

    def _handler_for(self, hub_key: int) -> Callable[[Message], None]:
        def on_next(message: Message) -> None:
            self._on_message(hub_key, message)

        return on_next

    def _on_message(self, hub_key: int, message: Message) -> None:
        if self._disposed or self._current is None or hub_key not in self._subscriptions:
            return
        if id(getattr(message, "sender_object", None)) not in self._watched_ids:
            return
        path = self._path_to_root(self._current)
        if path is not None:
            self._watch(path)
            return
        self._current = None
        self._release_watch()
        self._emit(None)

    def _emit(self, value: TVM | None) -> None:
        """Deliver *value* after the changes already being delivered.

        A raising subscriber does not stop later queued changes; the first
        failure is re-raised once the queue is drained.
        """
        self._pending.append(value)
        if self._emitting:
            return
        self._emitting = True
        first_error: BaseException | None = None
        try:
            while self._pending and not self._disposed:
                try:
                    self._changes.on_next(self._pending.popleft())
                except BaseException as error:
                    if first_error is None:
                        first_error = error
        finally:
            self._emitting = False
            if self._disposed:
                self._pending.clear()
        if first_error is not None:
            raise first_error
