"""Immutable fluent builders for AggregateVM1 through AggregateVM6.

Each setter returns a NEW builder instance via ``dataclasses.replace`` (BLD-001).
``build()`` validates required fields and raises ``BuilderValidationError`` on failure
(BLD-002).

See spec/08-aggregate-vm.md and spec/10-builders.md (arity 6 added per ADR-0034).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.builders import _validation
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
V6 = TypeVar("V6", bound=ComponentVMProto)


# ---------------------------------------------------------------------------
# AggregateVM1Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM1Builder(Generic[V1]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM1`.

    Required fields: ``name``, ``services(hub, dispatcher)``, ``component_1(factory)``.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVM1Builder[V1]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM1Builder[V1]:
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> AggregateVM1Builder[V1]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM1Builder[V1]:
        return dataclasses.replace(self, _factory1=factory)

    def build(self) -> AggregateVM1[V1]:
        """Validate and construct an :class:`~vmx.aggregates.AggregateVM1`.

        Raises :class:`~vmx.builders.exceptions.BuilderValidationError`
        if a required field is missing.
        """
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        if self._factory1 is None:
            raise BuilderValidationError("component_1")

        return AggregateVM1(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
        )


# ---------------------------------------------------------------------------
# AggregateVM2Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM2Builder(Generic[V1, V2]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM2`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVM2Builder[V1, V2]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM2Builder[V1, V2]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVM2Builder[V1, V2]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM2Builder[V1, V2]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVM2Builder[V1, V2]:
        return dataclasses.replace(self, _factory2=factory)

    def build(self) -> AggregateVM2[V1, V2]:
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")

        return AggregateVM2(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
        )


# ---------------------------------------------------------------------------
# AggregateVM3Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM3Builder(Generic[V1, V2, V3]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM3`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVM3Builder[V1, V2, V3]:
        return dataclasses.replace(self, _factory3=factory)

    def build(self) -> AggregateVM3[V1, V2, V3]:
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")
        if self._factory3 is None:
            raise BuilderValidationError("component_3")

        return AggregateVM3(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
        )


# ---------------------------------------------------------------------------
# AggregateVM4Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM4Builder(Generic[V1, V2, V3, V4]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM4`."""

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)
    _factory4: Callable[[], V4] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory3=factory)

    def component_4(self, factory: Callable[[], V4]) -> AggregateVM4Builder[V1, V2, V3, V4]:
        return dataclasses.replace(self, _factory4=factory)

    def build(self) -> AggregateVM4[V1, V2, V3, V4]:
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
        if self._factory1 is None:
            raise BuilderValidationError("component_1")
        if self._factory2 is None:
            raise BuilderValidationError("component_2")
        if self._factory3 is None:
            raise BuilderValidationError("component_3")
        if self._factory4 is None:
            raise BuilderValidationError("component_4")

        return AggregateVM4(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
            factory4=self._factory4,
        )


# ---------------------------------------------------------------------------
# AggregateVM5Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM5Builder(Generic[V1, V2, V3, V4, V5]):
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

    def name(self, value: str) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory3=factory)

    def component_4(self, factory: Callable[[], V4]) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory4=factory)

    def component_5(self, factory: Callable[[], V5]) -> AggregateVM5Builder[V1, V2, V3, V4, V5]:
        return dataclasses.replace(self, _factory5=factory)

    def build(self) -> AggregateVM5[V1, V2, V3, V4, V5]:
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
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
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
            factory4=self._factory4,
            factory5=self._factory5,
        )


# ---------------------------------------------------------------------------
# AggregateVM6Builder
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class AggregateVM6Builder(Generic[V1, V2, V3, V4, V5, V6]):
    """Immutable fluent builder for :class:`~vmx.aggregates.AggregateVM6`.

    Added in spec 2.2.0 per ADR-0034.
    """

    _name: str | None = dataclasses.field(default=None)
    _hint: str = dataclasses.field(default="")
    _hub: MessageHub[Message] | None = dataclasses.field(default=None)
    _dispatcher: Dispatcher | None = dataclasses.field(default=None)
    _factory1: Callable[[], V1] | None = dataclasses.field(default=None)
    _factory2: Callable[[], V2] | None = dataclasses.field(default=None)
    _factory3: Callable[[], V3] | None = dataclasses.field(default=None)
    _factory4: Callable[[], V4] | None = dataclasses.field(default=None)
    _factory5: Callable[[], V5] | None = dataclasses.field(default=None)
    _factory6: Callable[[], V6] | None = dataclasses.field(default=None)

    def name(self, value: str) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def component_1(self, factory: Callable[[], V1]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory1=factory)

    def component_2(self, factory: Callable[[], V2]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory2=factory)

    def component_3(self, factory: Callable[[], V3]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory3=factory)

    def component_4(self, factory: Callable[[], V4]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory4=factory)

    def component_5(self, factory: Callable[[], V5]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory5=factory)

    def component_6(self, factory: Callable[[], V6]) -> AggregateVM6Builder[V1, V2, V3, V4, V5, V6]:
        return dataclasses.replace(self, _factory6=factory)

    def build(self) -> AggregateVM6[V1, V2, V3, V4, V5, V6]:
        name = _validation.require_field(self._name, "name")
        hub, dispatcher = _validation.require_services(self._hub, self._dispatcher)
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
        if self._factory6 is None:
            raise BuilderValidationError("component_6")

        return AggregateVM6(
            name=name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            factory1=self._factory1,
            factory2=self._factory2,
            factory3=self._factory3,
            factory4=self._factory4,
            factory5=self._factory5,
            factory6=self._factory6,
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
    AggregateVM6,
)

__all__ = [
    "AggregateVM1Builder",
    "AggregateVM2Builder",
    "AggregateVM3Builder",
    "AggregateVM4Builder",
    "AggregateVM5Builder",
    "AggregateVM6Builder",
]
