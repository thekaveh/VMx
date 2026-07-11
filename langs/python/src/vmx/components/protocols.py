"""Component VM Protocols and ViewModelType enum.

See spec/05-component-vm.md §Members and spec/01-concepts.md §IComponentVM.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx

from vmx.commands.relay_command import RelayCommand
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHubProto

M = TypeVar("M")
M_co = TypeVar("M_co", covariant=True)  # for read-only protocol members


class ViewModelType(str, Enum):
    """Role discriminator for every VM variant.

    Inherits from str so values compare equal to their string equivalents
    (compatible with Python 3.10 which lacks StrEnum).

    Values match the string names used in the spec and C# enum.
    """

    COMPONENT = "Component"
    READONLY_COMPONENT = "ReadOnlyComponent"
    AGGREGATE = "Aggregate"
    GROUP = "Group"
    COMPOSITE = "Composite"


@runtime_checkable
class ComponentVMProto(Protocol):
    """Baseline interface for every ComponentVM variant.

    See spec/05-component-vm.md §Members and spec/01-concepts.md.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str: ...

    @property
    def hint(self) -> str: ...

    @property
    def type(self) -> ViewModelType: ...

    @property
    def is_current(self) -> bool: ...

    @property
    def is_constructed(self) -> bool: ...

    @property
    def status(self) -> ConstructionStatus: ...

    @property
    def hub(self) -> MessageHubProto[Message]: ...

    # ── Observable property changes ──────────────────────────────────────────
    @property
    def property_changed(self) -> rx.Observable[object]: ...

    # ── Built-in commands ────────────────────────────────────────────────────
    @property
    def select_command(self) -> RelayCommand: ...

    @property
    def deselect_command(self) -> RelayCommand: ...

    @property
    def select_next_command(self) -> RelayCommand: ...

    @property
    def select_previous_command(self) -> RelayCommand: ...

    @property
    def reconstruct_command(self) -> RelayCommand: ...

    # ── Lifecycle operations ─────────────────────────────────────────────────
    def can_construct(self) -> bool: ...

    def construct(self) -> None: ...

    def can_destruct(self) -> bool: ...

    def destruct(self) -> None: ...

    def can_reconstruct(self) -> bool: ...

    def reconstruct(self) -> None: ...

    def dispose(self) -> None: ...

    # ── Selection operations ─────────────────────────────────────────────────
    def can_select(self) -> bool: ...

    def select(self) -> None: ...

    def can_deselect(self) -> bool: ...

    def deselect(self) -> None: ...


@runtime_checkable
class ComponentVMOfProto(ComponentVMProto, Protocol, Generic[M]):
    """Extension of ComponentVMProto for the modeled (settable) variant.

    Adds a settable ``model`` property and derived ``modeled_hint``.
    """

    @property
    def model(self) -> M: ...

    @model.setter
    def model(self, value: M) -> None: ...

    @property
    def modeled_hint(self) -> str: ...

    def republish_model(self) -> None: ...


@runtime_checkable
class ReadonlyComponentVMOfProto(ComponentVMProto, Protocol, Generic[M_co]):
    """Extension of ComponentVMProto for the readonly modeled variant.

    Adds a read-only ``model`` property and derived ``modeled_hint``.
    The model type is covariant because it is only exposed via a getter.
    """

    @property
    def model(self) -> M_co: ...

    @property
    def modeled_hint(self) -> str: ...

    def republish_model(self) -> None: ...
