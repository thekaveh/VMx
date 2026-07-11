"""ForwardingComponentVM — forwarding decorator for ComponentVMOfProto[M].

Every public member delegates to ``_wrapped`` by default. Subclasses override
individual members to customise behaviour.

See spec/09-forwarding.md §ForwardingComponentVM and FWD-001/FWD-002 in
spec/12-conformance.md.
"""

from __future__ import annotations

from typing import Generic, TypeVar

import reactivex as rx

from vmx.commands.relay_command import RelayCommand
from vmx.components.protocols import ComponentVMOfProto, ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHubProto

M = TypeVar("M")


class ForwardingComponentVM(Generic[M]):
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
    def property_changed(self) -> rx.Observable[object]:
        return self._wrapped.property_changed

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
