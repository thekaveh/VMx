"""ForwardingComponentVM — forwarding decorator for ComponentVMOfProto[M].

Every public member delegates to ``_wrapped`` by default. Subclasses override
individual members to customise behaviour.

See spec/09-forwarding.md §ForwardingComponentVM and FWD-001/FWD-002 in
spec/12-conformance.md.
"""

from __future__ import annotations

from concurrent.futures import Future
from threading import RLock
from typing import Generic, TypeVar, cast

import reactivex as rx

from vmx.commands.relay_command import RelayCommand
from vmx.components.base import _ComponentVMBase, _ParentCompositeVM, _ParentTransfer
from vmx.components.protocols import ComponentVMOfProto, ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHubProto

M = TypeVar("M")


class _ForwardingParent(_ParentCompositeVM):
    def __init__(self, parent: _ParentCompositeVM, wrapper: ForwardingComponentVM[object]) -> None:
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
        return self._wrapper._wrapped if current is self._wrapper else current

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
        return self._parent.detach_for_transfer(self._wrapper)


class _WrappedParent(_ParentCompositeVM):
    """Map a new decorator's ownership operations to its already-owned inner."""

    def __init__(
        self,
        parent: _ParentCompositeVM,
        wrapper: ForwardingComponentVM[object],
        wrapped: _ComponentVMBase,
    ) -> None:
        self._parent = parent
        self._wrapper = wrapper
        self._wrapped = wrapped

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
        retained_wrapper = (
            self._parent._wrapper if isinstance(self._parent, _ForwardingParent) else None
        )
        staged = self._parent.detach_for_transfer(self._wrapped)

        def commit() -> None:
            try:
                staged.commit()
            finally:
                if retained_wrapper is not None and retained_wrapper is not self._wrapper:
                    retained_wrapper._parent = None

        return _ParentTransfer(commit, staged.rollback)


class ForwardingComponentVM(_ComponentVMBase, Generic[M]):
    """Forwarding decorator for :class:`~vmx.components.protocols.ComponentVMOfProto`.

    Every member delegates to the wrapped instance by default. Subclasses
    override individual members to customise behaviour.

    This is not abstract (no ABCMeta): the class is usable as-is; subclassing
    is expected rather than enforced. See spec/09-forwarding.md.

    Usage::

        class LoggingVM(ForwardingComponentVM[MyModel]):
            def __init__(self, inner: ComponentVMOfProto[MyModel]) -> None:
                super().__init__(inner)

            @property
            def hint(self) -> str:
                return super().hint
    """

    def __init__(self, wrapped: ComponentVMOfProto[M]) -> None:
        if wrapped is None:
            raise ValueError("wrapped must not be None")
        self._wrapped: ComponentVMOfProto[M] = wrapped
        self._parent: _ParentCompositeVM | None = None
        self._ownership_lock = RLock()
        self._ownership_in_progress = False

    # ── Identity ─────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._wrapped.name

    @property
    def hint(self) -> str:
        return self._wrapped.hint

    @property
    def type(self) -> ViewModelType:
        return self._wrapped.type

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_current(self) -> bool:
        return self._wrapped.is_current

    @property
    def is_constructed(self) -> bool:
        return self._wrapped.is_constructed

    @property
    def status(self) -> ConstructionStatus:
        return self._wrapped.status

    @property
    def hub(self) -> MessageHubProto[Message]:
        return self._wrapped.hub

    # ── Model ─────────────────────────────────────────────────────────────────

    @property
    def model(self) -> M:
        return self._wrapped.model

    @model.setter
    def model(self, value: M) -> None:
        self._wrapped.model = value

    @property
    def modeled_hint(self) -> str:
        return self._wrapped.modeled_hint

    def republish_model(self) -> None:
        self._wrapped.republish_model()

    # ── Observable property changes ───────────────────────────────────────────

    @property
    def property_changed(self) -> rx.Observable[str]:
        return cast(rx.Observable[str], self._wrapped.property_changed)

    # ── Built-in commands ─────────────────────────────────────────────────────

    @property
    def select_command(self) -> RelayCommand:
        return self._wrapped.select_command

    @property
    def deselect_command(self) -> RelayCommand:
        return self._wrapped.deselect_command

    @property
    def select_next_command(self) -> RelayCommand:
        return self._wrapped.select_next_command

    @property
    def select_previous_command(self) -> RelayCommand:
        return self._wrapped.select_previous_command

    @property
    def reconstruct_command(self) -> RelayCommand:
        return self._wrapped.reconstruct_command

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def can_construct(self) -> bool:
        return self._wrapped.can_construct()

    def construct(self) -> None:
        self._wrapped.construct()

    def can_destruct(self) -> bool:
        return self._wrapped.can_destruct()

    def destruct(self) -> None:
        self._wrapped.destruct()

    def can_reconstruct(self) -> bool:
        return self._wrapped.can_reconstruct()

    def reconstruct(self) -> None:
        self._wrapped.reconstruct()

    def dispose(self) -> None:
        self._wrapped.dispose()

    # ── Selection ─────────────────────────────────────────────────────────────

    def can_select(self) -> bool:
        return self._wrapped.can_select()

    def select(self) -> None:
        self._wrapped.select()

    def can_deselect(self) -> bool:
        return self._wrapped.can_deselect()

    def deselect(self) -> None:
        self._wrapped.deselect()

    def _set_parent(self, parent: _ParentCompositeVM | None) -> None:
        self._parent = parent
        wrapped = cast(_ComponentVMBase, self._wrapped)
        wrapped._set_parent(
            None
            if parent is None
            else _ForwardingParent(parent, cast(ForwardingComponentVM[object], self))
        )

    @property
    def _ownership_parent(self) -> _ParentCompositeVM | None:
        if self._parent is not None:
            return self._parent
        if not isinstance(self._wrapped, _ComponentVMBase):
            return None
        wrapped_parent = self._wrapped._ownership_parent
        if wrapped_parent is None:
            return None
        return _WrappedParent(
            wrapped_parent,
            cast(ForwardingComponentVM[object], self),
            self._wrapped,
        )

    def _set_is_current(self, value: bool) -> None:
        cast(_ComponentVMBase, self._wrapped)._set_is_current(value)

    def _commit_is_current(self, value: bool) -> bool:
        return cast(_ComponentVMBase, self._wrapped)._commit_is_current(value)

    def _publish_is_current(self) -> None:
        cast(_ComponentVMBase, self._wrapped)._publish_is_current()

    def _construct_future(self) -> Future[None]:
        return cast(_ComponentVMBase, self._wrapped)._construct_future()

    def _destruct_future(self) -> Future[None]:
        return cast(_ComponentVMBase, self._wrapped)._destruct_future()
