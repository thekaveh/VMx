"""AggregateVM1 through AggregateVM5 — fixed-arity tuples of heterogeneous component VMs.

Each AggregateVMN holds N component slots populated lazily by factories at construct time.
See spec/08-aggregate-vm.md and ADR-0007.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ComponentVMProto, ViewModelType
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

V1 = TypeVar("V1", bound=ComponentVMProto)
V2 = TypeVar("V2", bound=ComponentVMProto)
V3 = TypeVar("V3", bound=ComponentVMProto)
V4 = TypeVar("V4", bound=ComponentVMProto)
V5 = TypeVar("V5", bound=ComponentVMProto)


# ---------------------------------------------------------------------------
# AggregateVM1
# ---------------------------------------------------------------------------


class AggregateVM1(Generic[V1], _ComponentVMBase):
    """Arity-1 aggregate viewmodel. A fixed tuple of one heterogeneous component VM.

    The component slot is populated lazily on construct() by invoking the factory
    provided via the builder.

    See spec/08-aggregate-vm.md and ADR-0007.
    """

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        factory1: Callable[[], V1],
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._factory1: Callable[[], V1] = factory1
        self._component1: V1 | None = None

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.AGGREGATE

    @property
    def component_1(self) -> V1 | None:
        """The first (and only) component slot; None until construct() is called."""
        return self._component1

    def _on_construct(self) -> None:
        self._component1 = self._factory1()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_1"))
        self._raise_property_changed("component_1")
        self._component1.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()

    def _on_dispose(self) -> None:
        if self._component1 is not None:
            self._component1.dispose()


# ---------------------------------------------------------------------------
# AggregateVM2
# ---------------------------------------------------------------------------


class AggregateVM2(Generic[V1, V2], _ComponentVMBase):
    """Arity-2 aggregate viewmodel. A fixed tuple of two heterogeneous component VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        factory1: Callable[[], V1],
        factory2: Callable[[], V2],
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._factory1: Callable[[], V1] = factory1
        self._factory2: Callable[[], V2] = factory2
        self._component1: V1 | None = None
        self._component2: V2 | None = None

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.AGGREGATE

    @property
    def component_1(self) -> V1 | None:
        return self._component1

    @property
    def component_2(self) -> V2 | None:
        return self._component2

    def _on_construct(self) -> None:
        self._component1 = self._factory1()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_1"))
        self._raise_property_changed("component_1")

        self._component2 = self._factory2()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_2"))
        self._raise_property_changed("component_2")

        self._component1.construct()
        self._component2.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()
        if self._component2 is not None:
            self._component2.destruct()

    def _on_dispose(self) -> None:
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()


# ---------------------------------------------------------------------------
# AggregateVM3
# ---------------------------------------------------------------------------


class AggregateVM3(Generic[V1, V2, V3], _ComponentVMBase):
    """Arity-3 aggregate viewmodel. A fixed tuple of three heterogeneous component VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        factory1: Callable[[], V1],
        factory2: Callable[[], V2],
        factory3: Callable[[], V3],
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._factory1: Callable[[], V1] = factory1
        self._factory2: Callable[[], V2] = factory2
        self._factory3: Callable[[], V3] = factory3
        self._component1: V1 | None = None
        self._component2: V2 | None = None
        self._component3: V3 | None = None

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.AGGREGATE

    @property
    def component_1(self) -> V1 | None:
        return self._component1

    @property
    def component_2(self) -> V2 | None:
        return self._component2

    @property
    def component_3(self) -> V3 | None:
        return self._component3

    def _on_construct(self) -> None:
        self._component1 = self._factory1()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_1"))
        self._raise_property_changed("component_1")

        self._component2 = self._factory2()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_2"))
        self._raise_property_changed("component_2")

        self._component3 = self._factory3()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_3"))
        self._raise_property_changed("component_3")

        self._component1.construct()
        self._component2.construct()
        self._component3.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()
        if self._component2 is not None:
            self._component2.destruct()
        if self._component3 is not None:
            self._component3.destruct()

    def _on_dispose(self) -> None:
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()


# ---------------------------------------------------------------------------
# AggregateVM4
# ---------------------------------------------------------------------------


class AggregateVM4(Generic[V1, V2, V3, V4], _ComponentVMBase):
    """Arity-4 aggregate viewmodel. A fixed tuple of four heterogeneous component VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        factory1: Callable[[], V1],
        factory2: Callable[[], V2],
        factory3: Callable[[], V3],
        factory4: Callable[[], V4],
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._factory1: Callable[[], V1] = factory1
        self._factory2: Callable[[], V2] = factory2
        self._factory3: Callable[[], V3] = factory3
        self._factory4: Callable[[], V4] = factory4
        self._component1: V1 | None = None
        self._component2: V2 | None = None
        self._component3: V3 | None = None
        self._component4: V4 | None = None

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.AGGREGATE

    @property
    def component_1(self) -> V1 | None:
        return self._component1

    @property
    def component_2(self) -> V2 | None:
        return self._component2

    @property
    def component_3(self) -> V3 | None:
        return self._component3

    @property
    def component_4(self) -> V4 | None:
        return self._component4

    def _on_construct(self) -> None:
        self._component1 = self._factory1()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_1"))
        self._raise_property_changed("component_1")

        self._component2 = self._factory2()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_2"))
        self._raise_property_changed("component_2")

        self._component3 = self._factory3()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_3"))
        self._raise_property_changed("component_3")

        self._component4 = self._factory4()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_4"))
        self._raise_property_changed("component_4")

        self._component1.construct()
        self._component2.construct()
        self._component3.construct()
        self._component4.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()
        if self._component2 is not None:
            self._component2.destruct()
        if self._component3 is not None:
            self._component3.destruct()
        if self._component4 is not None:
            self._component4.destruct()

    def _on_dispose(self) -> None:
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()
        if self._component4 is not None:
            self._component4.dispose()


# ---------------------------------------------------------------------------
# AggregateVM5
# ---------------------------------------------------------------------------


class AggregateVM5(Generic[V1, V2, V3, V4, V5], _ComponentVMBase):
    """Arity-5 aggregate viewmodel. A fixed tuple of five heterogeneous component VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        factory1: Callable[[], V1],
        factory2: Callable[[], V2],
        factory3: Callable[[], V3],
        factory4: Callable[[], V4],
        factory5: Callable[[], V5],
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._factory1: Callable[[], V1] = factory1
        self._factory2: Callable[[], V2] = factory2
        self._factory3: Callable[[], V3] = factory3
        self._factory4: Callable[[], V4] = factory4
        self._factory5: Callable[[], V5] = factory5
        self._component1: V1 | None = None
        self._component2: V2 | None = None
        self._component3: V3 | None = None
        self._component4: V4 | None = None
        self._component5: V5 | None = None

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.AGGREGATE

    @property
    def component_1(self) -> V1 | None:
        return self._component1

    @property
    def component_2(self) -> V2 | None:
        return self._component2

    @property
    def component_3(self) -> V3 | None:
        return self._component3

    @property
    def component_4(self) -> V4 | None:
        return self._component4

    @property
    def component_5(self) -> V5 | None:
        return self._component5

    def _on_construct(self) -> None:
        self._component1 = self._factory1()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_1"))
        self._raise_property_changed("component_1")

        self._component2 = self._factory2()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_2"))
        self._raise_property_changed("component_2")

        self._component3 = self._factory3()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_3"))
        self._raise_property_changed("component_3")

        self._component4 = self._factory4()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_4"))
        self._raise_property_changed("component_4")

        self._component5 = self._factory5()
        self._hub.send(PropertyChangedMessage.create(self, self._name, "component_5"))
        self._raise_property_changed("component_5")

        self._component1.construct()
        self._component2.construct()
        self._component3.construct()
        self._component4.construct()
        self._component5.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()
        if self._component2 is not None:
            self._component2.destruct()
        if self._component3 is not None:
            self._component3.destruct()
        if self._component4 is not None:
            self._component4.destruct()
        if self._component5 is not None:
            self._component5.destruct()

    def _on_dispose(self) -> None:
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()
        if self._component4 is not None:
            self._component4.dispose()
        if self._component5 is not None:
            self._component5.dispose()
