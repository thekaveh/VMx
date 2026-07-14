"""AggregateVM1 through AggregateVM6 — fixed-arity tuples of heterogeneous component VMs.

Each AggregateVMN holds N component slots populated lazily by factories at construct time.
See spec/08-aggregate-vm.md and ADR-0007 (arity 6 added per ADR-0034).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.components.base import _ComponentVMBase, _dispose_children_then_self
from vmx.components.protocols import ComponentVMProto, ViewModelType
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

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        Tree traversal (``walk``/``walk_expanded``/``find``) uses this typed
        accessor instead of probing ``component_{i}`` name strings bounded at a
        fixed arity, so traversal stays correct for any arity — including a
        future AggregateVM7+.
        """
        slots: tuple[ComponentVMProto | None, ...] = (self._component1,)
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, the previous slot instance is in Destructed state but
        # still holds hub subscriptions and command Subjects. Dispose it before
        # overwriting so subscribers don't leak across the Reconstruct boundary.
        if self._component1 is not None:
            self._component1.dispose()
        self._component1 = self._factory1()
        self._notify_property_changed("component_1")
        self._component1.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): the component slot first, then self.
        Mirrors C# / TS / Swift AggregateVM1.Dispose so subscribers observe child
        Disposed transitions before the aggregate's own Disposed transition — a
        single dispose-ordering rule across all aggregate arities."""
        _dispose_children_then_self((self._component1,), super().dispose)


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

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        See ``AggregateVM1.components`` for the arity-independence rationale.
        """
        slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
        )
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()

        self._component1 = self._factory1()
        self._notify_property_changed("component_1")

        self._component2 = self._factory2()
        self._notify_property_changed("component_2")

        self._component1.construct()
        self._component2.construct()

    def _on_destruct(self) -> None:
        if self._component1 is not None:
            self._component1.destruct()
        if self._component2 is not None:
            self._component2.destruct()

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self((self._component1, self._component2), super().dispose)


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

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        See ``AggregateVM1.components`` for the arity-independence rationale.
        """
        slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
        )
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()

        self._component1 = self._factory1()
        self._notify_property_changed("component_1")

        self._component2 = self._factory2()
        self._notify_property_changed("component_2")

        self._component3 = self._factory3()
        self._notify_property_changed("component_3")

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

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self(
            (self._component1, self._component2, self._component3), super().dispose
        )


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

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        See ``AggregateVM1.components`` for the arity-independence rationale.
        """
        slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
        )
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()
        if self._component4 is not None:
            self._component4.dispose()

        self._component1 = self._factory1()
        self._notify_property_changed("component_1")

        self._component2 = self._factory2()
        self._notify_property_changed("component_2")

        self._component3 = self._factory3()
        self._notify_property_changed("component_3")

        self._component4 = self._factory4()
        self._notify_property_changed("component_4")

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

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self(
            (
                self._component1,
                self._component2,
                self._component3,
                self._component4,
            ),
            super().dispose,
        )


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

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        See ``AggregateVM1.components`` for the arity-independence rationale.
        """
        slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
            self._component5,
        )
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
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

        self._component1 = self._factory1()
        self._notify_property_changed("component_1")

        self._component2 = self._factory2()
        self._notify_property_changed("component_2")

        self._component3 = self._factory3()
        self._notify_property_changed("component_3")

        self._component4 = self._factory4()
        self._notify_property_changed("component_4")

        self._component5 = self._factory5()
        self._notify_property_changed("component_5")

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

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self(
            (
                self._component1,
                self._component2,
                self._component3,
                self._component4,
                self._component5,
            ),
            super().dispose,
        )


# ---------------------------------------------------------------------------
# AggregateVM6
# ---------------------------------------------------------------------------


class AggregateVM6(Generic[V1, V2, V3, V4, V5, V6], _ComponentVMBase):
    """Arity-6 aggregate viewmodel. A fixed tuple of six heterogeneous component VMs.

    Added in spec 2.2.0 per ADR-0034.
    """

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
        factory6: Callable[[], V6],
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
        self._factory6: Callable[[], V6] = factory6
        self._component1: V1 | None = None
        self._component2: V2 | None = None
        self._component3: V3 | None = None
        self._component4: V4 | None = None
        self._component5: V5 | None = None
        self._component6: V6 | None = None

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

    @property
    def component_6(self) -> V6 | None:
        return self._component6

    def components(self) -> list[ComponentVMProto]:
        """Component slots in declaration order; ``None`` slots omitted (VMX-137).

        See ``AggregateVM1.components`` for the arity-independence rationale.
        """
        slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
            self._component5,
            self._component6,
        )
        return [c for c in slots if c is not None]

    def _on_construct(self) -> None:
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
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
        if self._component6 is not None:
            self._component6.dispose()

        self._component1 = self._factory1()
        self._notify_property_changed("component_1")

        self._component2 = self._factory2()
        self._notify_property_changed("component_2")

        self._component3 = self._factory3()
        self._notify_property_changed("component_3")

        self._component4 = self._factory4()
        self._notify_property_changed("component_4")

        self._component5 = self._factory5()
        self._notify_property_changed("component_5")

        self._component6 = self._factory6()
        self._notify_property_changed("component_6")

        self._component1.construct()
        self._component2.construct()
        self._component3.construct()
        self._component4.construct()
        self._component5.construct()
        self._component6.construct()

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
        if self._component6 is not None:
            self._component6.destruct()

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self(
            (
                self._component1,
                self._component2,
                self._component3,
                self._component4,
                self._component5,
                self._component6,
            ),
            super().dispose,
        )
