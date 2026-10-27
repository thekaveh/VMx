"""Container membership shared by every forwarding decorator.

A decorator and its wrapped VM are one ownership identity (spec/09 §1-2,
FWD-002/FWD-004): the wrapped VM records the decorator's parent through an
adapter, so single-parent ownership, ``is_current`` and transfer all act on the
decorator that the parent actually holds. C# ``ForwardingMembership`` is the
counterpart.
"""

from __future__ import annotations

from abc import abstractmethod
from concurrent.futures import Future
from threading import RLock

from vmx.components.base import _ComponentVMBase, _ParentCompositeVM, _ParentTransfer


class _ForwardingParent(_ParentCompositeVM):
    def __init__(self, parent: _ParentCompositeVM, wrapper: _ForwardingMembership) -> None:
        self._parent = parent
        self._wrapper = wrapper

    @property
    def owner(self) -> _ComponentVMBase:
        return self._parent.owner

    @property
    def owner_parent(self) -> _ParentCompositeVM | None:
        return self._parent.owner_parent

    @property
    def current_child(self) -> object | None:
        current = self._parent.current_child
        return self._wrapper._wrapped_component if current is self._wrapper else current

    @property
    def supports_child_selection(self) -> bool:
        return self._parent.supports_child_selection

    def select_child(self, vm: _ComponentVMBase) -> None:
        self._parent.select_child(self._wrapper)

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        self._parent.deselect_child(self._wrapper)

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        return self._parent.contains_child(self._wrapper)

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        staged = self._parent.detach_for_transfer(self._wrapper)

        def commit() -> None:
            try:
                staged.commit()
            finally:
                self._wrapper._parent = None

        return _ParentTransfer(commit, staged.rollback)

    def retained_wrappers(self) -> tuple[_ForwardingMembership, ...]:
        wrappers: list[_ForwardingMembership] = []
        parent: _ParentCompositeVM = self
        while isinstance(parent, _ForwardingParent):
            wrappers.append(parent._wrapper)
            parent = parent._parent
        return tuple(wrappers)


class _WrappedParent(_ParentCompositeVM):
    """Map a new decorator's ownership operations to its already-owned inner."""

    def __init__(self, parent: _ParentCompositeVM, wrapper: _ForwardingMembership) -> None:
        self._parent = parent
        self._wrapper = wrapper
        self._wrapped = wrapper._wrapped_component

    @property
    def owner(self) -> _ComponentVMBase:
        return self._parent.owner

    @property
    def owner_parent(self) -> _ParentCompositeVM | None:
        return self._parent.owner_parent

    @property
    def current_child(self) -> object | None:
        current = self._parent.current_child
        return self._wrapper if current is self._wrapped else current

    @property
    def supports_child_selection(self) -> bool:
        return self._parent.supports_child_selection

    def select_child(self, vm: _ComponentVMBase) -> None:
        self._parent.select_child(self._wrapped)

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        self._parent.deselect_child(self._wrapped)

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        return self._parent.contains_child(self._wrapped)

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        retained_wrappers = (
            self._parent.retained_wrappers() if isinstance(self._parent, _ForwardingParent) else ()
        )
        staged = self._parent.detach_for_transfer(self._wrapped)

        def commit() -> None:
            try:
                staged.commit()
            finally:
                for retained_wrapper in retained_wrappers:
                    if retained_wrapper is not self._wrapper:
                        retained_wrapper._parent = None

        return _ParentTransfer(commit, staged.rollback)


class _ForwardingMembership(_ComponentVMBase):
    """Membership fields and hooks that forward to the wrapped component.

    Subclasses call :meth:`_init_membership` from ``__init__`` and implement
    :attr:`_wrapped_component`.
    """

    def _init_membership(self) -> None:
        self._parent: _ParentCompositeVM | None = None
        self._ownership_lock = RLock()
        self._ownership_in_progress = False

    @property
    @abstractmethod
    def _wrapped_component(self) -> _ComponentVMBase:
        """The wrapped VM, seen through its internal component surface."""

    def _set_parent(self, parent: _ParentCompositeVM | None) -> None:
        self._parent = parent
        self._wrapped_component._set_parent(
            None if parent is None else _ForwardingParent(parent, self)
        )

    @property
    def _ownership_identity(self) -> _ComponentVMBase:
        return self._wrapped_component._ownership_identity

    @property
    def _ownership_parent(self) -> _ParentCompositeVM | None:
        if self._parent is not None:
            return self._parent
        wrapped_parent = self._wrapped_component._ownership_parent
        if wrapped_parent is None:
            return None
        return _WrappedParent(wrapped_parent, self)

    def _set_is_current(self, value: bool) -> None:
        self._wrapped_component._set_is_current(value)

    def _commit_is_current(self, value: bool) -> bool:
        return self._wrapped_component._commit_is_current(value)

    def _publish_is_current(self) -> None:
        self._wrapped_component._publish_is_current()

    def _construct_future(self) -> Future[None]:
        return self._wrapped_component._construct_future()

    def _destruct_future(self) -> Future[None]:
        return self._wrapped_component._destruct_future()

    def _join_transition_future(self, *, construct: bool) -> Future[None]:
        return self._wrapped_component._join_transition_future(construct=construct)
