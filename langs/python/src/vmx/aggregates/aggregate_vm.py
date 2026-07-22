"""AggregateVM1 through AggregateVM6 — fixed-arity tuples of heterogeneous component VMs.

Each AggregateVMN holds N component slots populated lazily by factories at construct time.
See spec/08-aggregate-vm.md and ADR-0007 (arity 6 added per ADR-0034).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from vmx.components.base import (
    _ComponentVMBase,
    _dispose_children_then_self,
    _ParentCompositeVM,
    _ParentTransfer,
)
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


class _AggregateParent(_ParentCompositeVM):
    """Fixed-slot parent: selectable nowhere and never transferable out."""

    def __init__(self, aggregate: _AggregateVMBase) -> None:
        self._aggregate = aggregate

    @property
    def owner(self) -> _ComponentVMBase:
        return self._aggregate

    @property
    def owner_parent(self) -> _ParentCompositeVM | None:
        return self._aggregate._parent

    @property
    def current_child(self) -> None:
        return None

    @property
    def supports_child_selection(self) -> bool:
        return False

    def select_child(self, vm: _ComponentVMBase) -> None:
        del vm

    def deselect_child(self, vm: _ComponentVMBase) -> None:
        del vm

    def contains_child(self, vm: _ComponentVMBase) -> bool:
        identity = vm._ownership_identity
        return any(
            isinstance(child, _ComponentVMBase) and child._ownership_identity is identity
            for child in self._aggregate.components()
        )

    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer:
        del vm
        raise ValueError("a fixed aggregate slot cannot be transferred")


class _AggregateVMBase(_ComponentVMBase):
    """Shared exclusive-parent wiring for fixed aggregate slots."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._aggregate_parent = _AggregateParent(self)

    def components(self) -> list[ComponentVMProto]:
        raise NotImplementedError

    def _validate_new_slots(self, slots: tuple[ComponentVMProto, ...]) -> None:
        identities: set[int] = set()
        for child in slots:
            identity = child._ownership_identity if isinstance(child, _ComponentVMBase) else child
            if id(identity) in identities:
                raise ValueError(
                    "aggregate factories returned the same canonical component identity twice"
                )
            identities.add(id(identity))
            if isinstance(child, _ComponentVMBase):
                ownership_parent = child._ownership_parent
                if ownership_parent is not None:
                    if not (
                        ownership_parent is self._aggregate_parent
                        and self._aggregate_parent.contains_child(child)
                    ):
                        raise ValueError(f"component {child.name!r} already has a parent")
            cursor: _ParentCompositeVM | None = self._aggregate_parent
            while cursor is not None:
                if cursor.owner._ownership_identity is identity:
                    raise ValueError("aggregate ownership would create a parent cycle")
                cursor = cursor.owner_parent

    def _replace_slot_parents(
        self,
        old_slots: tuple[ComponentVMProto | None, ...],
        new_slots: tuple[ComponentVMProto, ...],
    ) -> None:
        for child in old_slots:
            if isinstance(child, _ComponentVMBase) and child._parent is self._aggregate_parent:
                child._set_parent(None)
        for child in new_slots:
            if isinstance(child, _ComponentVMBase):
                child._set_parent(self._aggregate_parent)


# ---------------------------------------------------------------------------
# AggregateVM1
# ---------------------------------------------------------------------------


class AggregateVM1(Generic[V1], _AggregateVMBase):
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
        next1 = self._factory1()
        self._validate_new_slots((next1,))
        old_slots: tuple[ComponentVMProto | None, ...] = (self._component1,)
        # On Reconstruct, the previous slot instance is in Destructed state but
        # still holds hub subscriptions and command Subjects. Dispose it before
        # overwriting so subscribers don't leak across the Reconstruct boundary.
        if self._component1 is not None:
            self._component1.dispose()
        self._component1 = next1
        self._replace_slot_parents(old_slots, (next1,))
        self._notify_property_changed("component_1")
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): the component slot first, then self.
        Mirrors C# / TS / Swift AggregateVM1.Dispose so subscribers observe child
        Disposed transitions before the aggregate's own Disposed transition — a
        single dispose-ordering rule across all aggregate arities."""
        _dispose_children_then_self((self._component1,), super().dispose)


# ---------------------------------------------------------------------------
# AggregateVM2
# ---------------------------------------------------------------------------


class AggregateVM2(Generic[V1, V2], _AggregateVMBase):
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
        next1 = self._factory1()
        next2 = self._factory2()
        self._validate_new_slots((next1, next2))
        old_slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
        )
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()

        self._component1 = next1
        self._notify_property_changed("component_1")

        self._component2 = next2
        self._replace_slot_parents(old_slots, (next1, next2))
        self._notify_property_changed("component_2")

        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self((self._component1, self._component2), super().dispose)


# ---------------------------------------------------------------------------
# AggregateVM3
# ---------------------------------------------------------------------------


class AggregateVM3(Generic[V1, V2, V3], _AggregateVMBase):
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
        next1 = self._factory1()
        next2 = self._factory2()
        next3 = self._factory3()
        self._validate_new_slots((next1, next2, next3))
        old_slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
        )
        # On Reconstruct, dispose previous slot instances before overwriting
        # so their hub subscriptions and command Subjects don't leak.
        if self._component1 is not None:
            self._component1.dispose()
        if self._component2 is not None:
            self._component2.dispose()
        if self._component3 is not None:
            self._component3.dispose()

        self._component1 = next1
        self._notify_property_changed("component_1")

        self._component2 = next2
        self._notify_property_changed("component_2")

        self._component3 = next3
        self._replace_slot_parents(old_slots, (next1, next2, next3))
        self._notify_property_changed("component_3")

        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

    def dispose(self) -> None:
        """Depth-first dispose (LIFE-013): each component slot first, then self.
        See AggregateVM1.dispose for the cross-flavor ordering rationale."""
        _dispose_children_then_self(
            (self._component1, self._component2, self._component3), super().dispose
        )


# ---------------------------------------------------------------------------
# AggregateVM4
# ---------------------------------------------------------------------------


class AggregateVM4(Generic[V1, V2, V3, V4], _AggregateVMBase):
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
        next1 = self._factory1()
        next2 = self._factory2()
        next3 = self._factory3()
        next4 = self._factory4()
        self._validate_new_slots((next1, next2, next3, next4))
        old_slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
        )
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

        self._component1 = next1
        self._notify_property_changed("component_1")

        self._component2 = next2
        self._notify_property_changed("component_2")

        self._component3 = next3
        self._notify_property_changed("component_3")

        self._component4 = next4
        self._replace_slot_parents(old_slots, (next1, next2, next3, next4))
        self._notify_property_changed("component_4")

        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

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


class AggregateVM5(Generic[V1, V2, V3, V4, V5], _AggregateVMBase):
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
        next1 = self._factory1()
        next2 = self._factory2()
        next3 = self._factory3()
        next4 = self._factory4()
        next5 = self._factory5()
        self._validate_new_slots((next1, next2, next3, next4, next5))
        old_slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
            self._component5,
        )
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

        self._component1 = next1
        self._notify_property_changed("component_1")

        self._component2 = next2
        self._notify_property_changed("component_2")

        self._component3 = next3
        self._notify_property_changed("component_3")

        self._component4 = next4
        self._notify_property_changed("component_4")

        self._component5 = next5
        self._replace_slot_parents(old_slots, (next1, next2, next3, next4, next5))
        self._notify_property_changed("component_5")

        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

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


class AggregateVM6(Generic[V1, V2, V3, V4, V5, V6], _AggregateVMBase):
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
        next1 = self._factory1()
        next2 = self._factory2()
        next3 = self._factory3()
        next4 = self._factory4()
        next5 = self._factory5()
        next6 = self._factory6()
        self._validate_new_slots((next1, next2, next3, next4, next5, next6))
        old_slots: tuple[ComponentVMProto | None, ...] = (
            self._component1,
            self._component2,
            self._component3,
            self._component4,
            self._component5,
            self._component6,
        )
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

        self._component1 = next1
        self._notify_property_changed("component_1")

        self._component2 = next2
        self._notify_property_changed("component_2")

        self._component3 = next3
        self._notify_property_changed("component_3")

        self._component4 = next4
        self._notify_property_changed("component_4")

        self._component5 = next5
        self._notify_property_changed("component_5")

        self._component6 = next6
        self._replace_slot_parents(old_slots, (next1, next2, next3, next4, next5, next6))
        self._notify_property_changed("component_6")

        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.components(), construct=False)
        )

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
