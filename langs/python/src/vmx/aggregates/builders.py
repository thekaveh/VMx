"""Immutable fluent builders for AggregateVM1 through AggregateVM5.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002).

See spec/08-aggregate-vm.md and spec/10-builders.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.builders.exceptions import BuilderValidationError
from vmx.components.protocols import ComponentVMProto
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

V1 = TypeVar("V1", bound=ComponentVMProto)
V2 = TypeVar("V2", bound=ComponentVMProto)
V3 = TypeVar("V3", bound=ComponentVMProto)
V4 = TypeVar("V4", bound=ComponentVMProto)
V5 = TypeVar("V5", bound=ComponentVMProto)


# ---------------------------------------------------------------------------
# AggregateVMBuilder1
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVMBuilder1(Generic[V1]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM1`.

    Required fields: ``name``, ``services(hub, dispatcher)``, ``component_1(factory)``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVMBuilder1[V1]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVMBuilder1[V1]:
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> AggregateVMBuilder1[V1]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVMBuilder1[V1]:
        return dataclasses.replace(self, _factory1=factory)

    def build(self) -> AggregateVM1[V1]:
        """Validate and construct an :class:`~vmx.aggregates.AggregateVM1`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        if self._name is None:
            raise BuilderValidationError("name")
        if self._hub is None:
            raise BuilderValidationError("hub")
        if self._dispatcher is None:
            raise BuilderValidationError("dispatcher")
        if self._factory1 is None:
            raise BuilderValidationError("component_1")

        return AggregateVM1(
            name=self._name,
            hint=self._hint,
            hub=self._hub,
            dispatcher=self._dispatcher,
            factory1=self._factory1,
        )


# ---------------------------------------------------------------------------
# AggregateVMBuilder2
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVMBuilder2(Generic[V1, V2]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM2`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVMBuilder2[V1, V2]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVMBuilder2[V1, V2]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVMBuilder2[V1, V2]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVMBuilder2[V1, V2]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVMBuilder2[V1, V2]:
        return dataclasses.replace(self, _factory2=factory)

    def build(self) -> AggregateVM2[V1, V2]:
        if self._name is None:
            raise BuilderValidationError("name")
        if self._hub is None:
            raise BuilderValidationError("hub")
        if self._dispatcher is None:
            raise BuilderValidationError("dispatcher")
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")

        return AggregateVM2(
            name=self._name,
            hint=self._hint,
            hub=self._hub,
            dispatcher=self._dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
        )


# ---------------------------------------------------------------------------
# AggregateVMBuilder3
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVMBuilder3(Generic[V1, V2, V3]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM3`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVMBuilder3[V1, V2, V3]:
        return dataclasses.replace(self, _factory3=factory)

    def build(self) -> AggregateVM3[V1, V2, V3]:
        if self._name is None:
            raise BuilderValidationError("name")
        if self._hub is None:
            raise BuilderValidationError("hub")
        if self._dispatcher is None:
            raise BuilderValidationError("dispatcher")
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")
        if self._factory3 is None:
            raise BuilderValidationError("component_3")

        return AggregateVM3(
            name=self._name,
            hint=self._hint,
            hub=self._hub,
            dispatcher=self._dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
        )


# ---------------------------------------------------------------------------
# AggregateVMBuilder4
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVMBuilder4(Generic[V1, V2, V3, V4]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM4`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)
    _factory4: Callable[[], V4] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory3=factory)

    def component_4(self, factory: Callable[[], V4]) -> AggregateVMBuilder4[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory4=factory)

    def build(self) -> AggregateVM4[V1, V2, V3, V4]:
        if self._name is None:
            raise BuilderValidationError("name")
        if self._hub is None:
            raise BuilderValidationError("hub")
        if self._dispatcher is None:
            raise BuilderValidationError("dispatcher")
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")
        if self._factory3 is None:
            raise BuilderValidationError("component_3")
        if self._factory4 is None:
            raise BuilderValidationError("component_4")

        return AggregateVM4(
            name=self._name,
            hint=self._hint,
            hub=self._hub,
            dispatcher=self._dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
            factory4=self._factory4,
        )


# ---------------------------------------------------------------------------
# AggregateVMBuilder5
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVMBuilder5(Generic[V1, V2, V3, V4, V5]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM5`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)
    _factory4: Callable[[], V4] | None = dataclasses.field(default=None)
    _factory5: Callable[[], V5] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory3=factory)

    def component_4(self, factory: Callable[[], V4]) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory4=factory)

    def component_5(self, factory: Callable[[], V5]) -> AggregateVMBuilder5[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory5=factory)

    def build(self) -> AggregateVM5[V1, V2, V3, V4, V5]:
        if self._name is None:
            raise BuilderValidationError("name")
        if self._hub is None:
            raise BuilderValidationError("hub")
        if self._dispatcher is None:
            raise BuilderValidationError("dispatcher")
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")
        if self._factory3 is None:
            raise BuilderValidationError("component_3")
        if self._factory4 is None:
            raise BuilderValidationError("component_4")
        if self._factory5 is None:
            raise BuilderValidationError("component_5")

        return AggregateVM5(
            name=self._name,
            hint=self._hint,
            hub=self._hub,
            dispatcher=self._dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
            factory4=self._factory4,
            factory5=self._factory5,
        )


# Forward references — the VM classes are defined in aggregate_vm.py which
# imports from this module's dependencies only (not this file), so we import
# here for type annotations.
from vmx.aggregates.aggregate_vm import (  # noqa: E402
    AggregateVM1,
    AggregateVM2,
    AggregateVM3,
    AggregateVM4,
    AggregateVM5,
)

__all__ = [
    "AggregateVMBuilder1",
    "AggregateVMBuilder2",
    "AggregateVMBuilder3",
    "AggregateVMBuilder4",
    "AggregateVMBuilder5",
]
