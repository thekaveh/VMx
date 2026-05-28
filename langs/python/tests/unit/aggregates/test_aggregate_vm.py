"""Unit tests for AggregateVM1 through AggregateVM5.

Tests verify:
- Identity (name, hint, type=AGGREGATE)
- Builder fluent API (BLD-001 — setter returns new instance)
- Builder validation (BLD-002 — missing required field raises)
- component_N is None before construct, populated after
- construct() populates and constructs all component slots
- PropertyChangedMessage emitted for each component slot on construct
- destruct() destructs all component slots
- dispose() cascades to all components
- All five arities
"""

from __future__ import annotations

import pytest

from vmx.aggregates.aggregate_vm import AggregateVM3
from vmx.aggregates.builders import (
    AggregateVMBuilder1,
    AggregateVMBuilder2,
    AggregateVMBuilder3,
    AggregateVMBuilder4,
    AggregateVMBuilder5,
)
from vmx.builders.exceptions import BuilderValidationError
from vmx.components.builders import ComponentVMBuilder
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_hub() -> MessageHub[object]:
    return MessageHub()


def _make_dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _make_child(hub: MessageHub[object], dispatcher: RxDispatcher, name: str = "child") -> object:
    return ComponentVMBuilder().name(name).services(hub, dispatcher).build()


# ---------------------------------------------------------------------------
# AggregateVM1 — identity and type
# ---------------------------------------------------------------------------


class TestAggregateVM1Identity:
    def test_name_set_correctly(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg-1")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.name == "agg-1"

    def test_hint_defaults_to_empty(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.hint == ""

    def test_hint_set_correctly(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .hint("my hint")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.hint == "my hint"

    def test_type_is_aggregate(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.type == ViewModelType.AGGREGATE

    def test_initial_status_is_destructed(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.status == ConstructionStatus.DESTRUCTED

    def test_component_1_is_none_before_construct(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        assert agg.component_1 is None


# ---------------------------------------------------------------------------
# AggregateVM1 — lifecycle
# ---------------------------------------------------------------------------


class TestAggregateVM1Lifecycle:
    def test_construct_populates_component_1(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .build()
        )
        agg.construct()
        assert agg.component_1 is not None
        assert agg.component_1.name == "c1"  # type: ignore[union-attr]

    def test_construct_makes_agg_constructed(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        agg.construct()
        assert agg.status == ConstructionStatus.CONSTRUCTED
        assert agg.is_constructed

    def test_construct_constructs_child(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        agg.construct()
        assert agg.component_1 is not None
        assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]

    def test_construct_emits_property_changed_for_component_1(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        prop_msgs: list[PropertyChangedMessage[object]] = []
        hub.messages.subscribe(
            lambda m: (
                prop_msgs.append(m)  # type: ignore[arg-type]
                if isinstance(m, PropertyChangedMessage) and m.property_name == "component_1"
                else None
            )
        )
        agg.construct()
        assert any(m.property_name == "component_1" for m in prop_msgs)

    def test_destruct_destructs_child(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        agg.construct()
        agg.destruct()
        assert agg.status == ConstructionStatus.DESTRUCTED
        assert agg.component_1 is not None
        assert agg.component_1.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]

    def test_dispose_cascades_to_child(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder1()
            .name("agg")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher))
            .build()
        )
        agg.construct()
        child = agg.component_1
        agg.dispose()
        assert agg.status == ConstructionStatus.DISPOSED
        assert child is not None
        assert child.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# AggregateVM1 builder validation (BLD-001, BLD-002)
# ---------------------------------------------------------------------------


class TestAggregateVMBuilder1Validation:
    def test_setter_returns_new_instance(self) -> None:
        b1 = AggregateVMBuilder1()
        b2 = b1.name("agg")
        assert b1 is not b2
        assert b1._name is None
        assert b2._name == "agg"

    def test_missing_name_raises(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            AggregateVMBuilder1().services(hub, dispatcher).component_1(lambda: None).build()  # type: ignore[arg-type,return-value]
        assert exc_info.value.missing_field == "name"

    def test_missing_hub_raises(self) -> None:
        with pytest.raises(BuilderValidationError) as exc_info:
            AggregateVMBuilder1().name("agg").component_1(lambda: None).build()  # type: ignore[arg-type,return-value]
        assert exc_info.value.missing_field == "hub"

    def test_missing_component_1_raises(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            AggregateVMBuilder1().name("agg").services(hub, dispatcher).build()
        assert exc_info.value.missing_field == "component_1"


# ---------------------------------------------------------------------------
# AggregateVM2 — both components constructed
# ---------------------------------------------------------------------------


class TestAggregateVM2:
    def test_component_1_and_2_populated_after_construct(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder2()
            .name("agg2")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .build()
        )
        agg.construct()
        assert agg.component_1 is not None
        assert agg.component_2 is not None
        assert agg.component_1.name == "c1"  # type: ignore[union-attr]
        assert agg.component_2.name == "c2"  # type: ignore[union-attr]

    def test_both_children_constructed_after_agg_construct(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder2()
            .name("agg2")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .build()
        )
        agg.construct()
        assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.status == ConstructionStatus.CONSTRUCTED

    def test_both_children_destructed_after_agg_destruct(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder2()
            .name("agg2")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .build()
        )
        agg.construct()
        agg.destruct()
        assert agg.component_1.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]

    def test_property_changed_emitted_for_each_component(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder2()
            .name("agg2")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .build()
        )
        prop_names: list[str] = []
        hub.messages.subscribe(
            lambda m: (
                prop_names.append(m.property_name)  # type: ignore[union-attr]
                if isinstance(m, PropertyChangedMessage)
                and m.property_name in ("component_1", "component_2")
                and m.sender is agg
                else None
            )
        )
        agg.construct()
        assert "component_1" in prop_names
        assert "component_2" in prop_names

    def test_builder_missing_component_2_raises(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            (
                AggregateVMBuilder2()
                .name("agg2")
                .services(hub, dispatcher)
                .component_1(lambda: _make_child(hub, dispatcher))
                .build()
            )
        assert exc_info.value.missing_field == "component_2"


# ---------------------------------------------------------------------------
# AggregateVM3 — three components
# ---------------------------------------------------------------------------


class TestAggregateVM3:
    def _build_agg3(self) -> tuple[AggregateVM3[object, object, object], MessageHub[object]]:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder3()
            .name("agg3")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .component_3(lambda: _make_child(hub, dispatcher, "c3"))
            .build()
        )
        return agg, hub  # type: ignore[return-value]

    def test_all_three_components_populated(self) -> None:
        agg, _ = self._build_agg3()
        agg.construct()
        assert agg.component_1 is not None
        assert agg.component_2 is not None
        assert agg.component_3 is not None

    def test_all_three_children_constructed(self) -> None:
        agg, _ = self._build_agg3()
        agg.construct()
        assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_3.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]

    def test_property_changed_for_all_three(self) -> None:
        agg, hub = self._build_agg3()
        prop_names: list[str] = []
        hub.messages.subscribe(
            lambda m: (
                prop_names.append(m.property_name)  # type: ignore[union-attr]
                if isinstance(m, PropertyChangedMessage)
                and m.sender is agg
                and m.property_name in ("component_1", "component_2", "component_3")
                else None
            )
        )
        agg.construct()
        assert "component_1" in prop_names
        assert "component_2" in prop_names
        assert "component_3" in prop_names


# ---------------------------------------------------------------------------
# AggregateVM4 and AggregateVM5 — smoke tests
# ---------------------------------------------------------------------------


class TestAggregateVM4:
    def test_all_four_children_constructed(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder4()
            .name("agg4")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .component_3(lambda: _make_child(hub, dispatcher, "c3"))
            .component_4(lambda: _make_child(hub, dispatcher, "c4"))
            .build()
        )
        agg.construct()
        assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_3.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_4.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.status == ConstructionStatus.CONSTRUCTED


class TestAggregateVM5:
    def test_all_five_children_constructed_and_agg_is_last(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder5()
            .name("agg5")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .component_3(lambda: _make_child(hub, dispatcher, "c3"))
            .component_4(lambda: _make_child(hub, dispatcher, "c4"))
            .component_5(lambda: _make_child(hub, dispatcher, "c5"))
            .build()
        )
        agg.construct()
        assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_3.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_4.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.component_5.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
        assert agg.status == ConstructionStatus.CONSTRUCTED

    def test_all_five_children_destructed_after_agg_destruct(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder5()
            .name("agg5")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .component_3(lambda: _make_child(hub, dispatcher, "c3"))
            .component_4(lambda: _make_child(hub, dispatcher, "c4"))
            .component_5(lambda: _make_child(hub, dispatcher, "c5"))
            .build()
        )
        agg.construct()
        agg.destruct()
        assert agg.component_1.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert agg.component_3.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert agg.component_4.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert agg.component_5.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]

    def test_dispose_cascades_to_all_five(self) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = (
            AggregateVMBuilder5()
            .name("agg5")
            .services(hub, dispatcher)
            .component_1(lambda: _make_child(hub, dispatcher, "c1"))
            .component_2(lambda: _make_child(hub, dispatcher, "c2"))
            .component_3(lambda: _make_child(hub, dispatcher, "c3"))
            .component_4(lambda: _make_child(hub, dispatcher, "c4"))
            .component_5(lambda: _make_child(hub, dispatcher, "c5"))
            .build()
        )
        agg.construct()
        agg.dispose()
        assert agg.component_1.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert agg.component_2.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert agg.component_3.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert agg.component_4.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert agg.component_5.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert agg.status == ConstructionStatus.DISPOSED


# ---------------------------------------------------------------------------
# Reconstruct / slot-dispose regression guard
# ---------------------------------------------------------------------------


def test_aggregate_reconstruct_disposes_previous_slot() -> None:
    """Regression: reconstruct() must dispose the previous _component1 before
    overwriting it with fresh factory output. Without the guard, the
    previous slot's hub subscriptions and Subjects would leak (commit
    cdefcb1; C# parallel at 560be45).
    """
    hub = _make_hub()
    dispatcher = _make_dispatcher()

    agg = (
        AggregateVMBuilder1()
        .name("agg1")
        .services(hub, dispatcher)
        .component_1(lambda: _make_child(hub, dispatcher, "slot1"))
        .build()
    )

    agg.construct()
    first = agg.component_1
    assert first is not None
    assert first.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]

    # reconstruct() destructs then re-constructs; with the parity fix in
    # cdefcb1, the previous _component1 is disposed before the new
    # factory output replaces it.
    agg.reconstruct()

    second = agg.component_1
    assert second is not None
    assert second is not first, "reconstruct must produce a fresh slot instance"
    assert second.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert first.status == ConstructionStatus.DISPOSED, (  # type: ignore[union-attr]
        "previous slot must be Disposed, not lingering in Destructed state"
    )
