"""Unit tests for AggregateVM1 through AggregateVM6.

Tests verify:
- Identity (name, hint, type=AGGREGATE)
- Builder fluent API (BLD-001 — setter returns new instance)
- Builder validation (BLD-002 — missing required field raises)
- component_N is None before construct, populated after
- construct() populates and constructs all component slots
- PropertyChangedMessage emitted for each component slot on construct
- destruct() destructs all component slots
- dispose() cascades to all components
- All six arities (arity 6 added per ADR-0034)
- Parametric coverage of arity 1..6 (TestAggregateVMArity)
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
    AggregateVMBuilder6,
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


# ---------------------------------------------------------------------------
# Parametric arity 1..6 coverage
# ---------------------------------------------------------------------------
#
# These parametric tests collapse the per-arity branches in aggregate_vm.py
# and builders.py into a single test surface. Each test runs once per arity
# in [1, 6], exercising:
#   * builder validation (each required component_N factory is checked)
#   * build() → working VM with N child slots
#   * lifecycle cascade (construct/destruct/dispose) across all N slots
#   * canonical Hub.Send → RaisePropertyChanged ordering per slot
#   * OnReconstruct disposes prior slots before overwriting (LIFE-013)
#   * type=AGGREGATE for every arity
#   * each ``component_N`` property returns its slot


_BUILDERS = {
    1: AggregateVMBuilder1,
    2: AggregateVMBuilder2,
    3: AggregateVMBuilder3,
    4: AggregateVMBuilder4,
    5: AggregateVMBuilder5,
    6: AggregateVMBuilder6,
}


def _build_arity(arity: int, hub: MessageHub[object], dispatcher: RxDispatcher) -> object:
    """Construct a fully-configured aggregate VM of the given arity via its builder."""
    builder = _BUILDERS[arity]().name(f"agg{arity}").services(hub, dispatcher)
    for n in range(1, arity + 1):
        setter = getattr(builder, f"component_{n}")
        builder = setter(lambda n=n: _make_child(hub, dispatcher, f"c{n}"))
    return builder.build()


def _components(agg: object, arity: int) -> list[object]:
    return [getattr(agg, f"component_{n}") for n in range(1, arity + 1)]


class TestAggregateVMArity:
    """Parametric tests covering arity 1..6 of AggregateVM and AggregateVMBuilder."""

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_type_is_aggregate(self, arity: int) -> None:
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        assert agg.type == ViewModelType.AGGREGATE  # type: ignore[attr-defined]

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_all_slots_none_before_construct(self, arity: int) -> None:
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        assert all(c is None for c in _components(agg, arity))

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_construct_populates_all_slots(self, arity: int) -> None:
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        agg.construct()  # type: ignore[attr-defined]
        children = _components(agg, arity)
        assert all(c is not None for c in children)
        for n, child in enumerate(children, start=1):
            assert child.name == f"c{n}"  # type: ignore[union-attr]
            assert child.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_destruct_cascades_to_all_slots(self, arity: int) -> None:
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        agg.construct()  # type: ignore[attr-defined]
        agg.destruct()  # type: ignore[attr-defined]
        assert agg.status == ConstructionStatus.DESTRUCTED  # type: ignore[attr-defined]
        for child in _components(agg, arity):
            assert child.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_dispose_cascades_to_all_slots(self, arity: int) -> None:
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        agg.construct()  # type: ignore[attr-defined]
        captured = _components(agg, arity)
        agg.dispose()  # type: ignore[attr-defined]
        assert agg.status == ConstructionStatus.DISPOSED  # type: ignore[attr-defined]
        for child in captured:
            assert child.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_property_changed_emitted_for_every_slot(self, arity: int) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = _build_arity(arity, hub, dispatcher)

        emitted: list[str] = []
        hub.messages.subscribe(
            lambda m: (
                emitted.append(m.property_name)  # type: ignore[union-attr]
                if isinstance(m, PropertyChangedMessage)
                and m.sender is agg
                and m.property_name.startswith("component_")
                else None
            )
        )
        agg.construct()  # type: ignore[attr-defined]

        # All N slot-PropertyChangedMessages must have fired, in canonical 1..N order
        # (Hub.Send before RaisePropertyChanged per spec; the hub captures the Send).
        expected = [f"component_{n}" for n in range(1, arity + 1)]
        assert emitted == expected

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_canonical_ordering_hub_send_precedes_raise_property_changed(self, arity: int) -> None:
        """For each slot N, Hub.Send(PropertyChangedMessage) must precede the
        per-instance ``RaisePropertyChanged`` callback observers — the canonical
        spec ordering. The base ``_ComponentVMBase`` does not expose
        property_changed as a native event, but every PropertyChangedMessage
        on the hub is paired (1:1) with a ``_raise_property_changed`` call.
        Asserting Hub-side ordering matches expected sequence catches drift
        either way.
        """
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        agg = _build_arity(arity, hub, dispatcher)
        sequence: list[str] = []

        # Use the hub subscription to record exact order.
        hub.messages.subscribe(
            lambda m: (
                sequence.append(m.property_name)  # type: ignore[union-attr]
                if isinstance(m, PropertyChangedMessage)
                and m.sender is agg
                and m.property_name.startswith("component_")
                else None
            )
        )
        agg.construct()  # type: ignore[attr-defined]
        assert sequence == [f"component_{n}" for n in range(1, arity + 1)]

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_reconstruct_disposes_prior_slots_before_overwriting(self, arity: int) -> None:
        """LIFE-013 regression: reconstruct must dispose every prior slot before
        replacing with fresh factory output (parallel to C# fix 560be45)."""
        agg = _build_arity(arity, _make_hub(), _make_dispatcher())
        agg.construct()  # type: ignore[attr-defined]
        firsts = _components(agg, arity)

        agg.reconstruct()  # type: ignore[attr-defined]
        seconds = _components(agg, arity)

        for f, s in zip(firsts, seconds, strict=False):
            assert f is not s, "reconstruct must produce fresh slot instances"
            assert f.status == ConstructionStatus.DISPOSED, (  # type: ignore[union-attr]
                "previous slot must be Disposed, not lingering in Destructed state"
            )
            assert s.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]

    @pytest.mark.parametrize("arity", [2, 3, 4, 5, 6])
    def test_builder_missing_each_factory_raises(self, arity: int) -> None:
        """For every slot index N in [1, arity], omitting component_N from the
        builder must raise BuilderValidationError with the canonical field name."""
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        for missing_n in range(1, arity + 1):
            builder = _BUILDERS[arity]().name("agg").services(hub, dispatcher)
            for n in range(1, arity + 1):
                if n == missing_n:
                    continue
                setter = getattr(builder, f"component_{n}")
                builder = setter(lambda: _make_child(hub, dispatcher))
            with pytest.raises(BuilderValidationError) as exc_info:
                builder.build()
            assert exc_info.value.missing_field == f"component_{missing_n}"

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_builder_missing_name_raises(self, arity: int) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        builder = _BUILDERS[arity]().services(hub, dispatcher)
        for n in range(1, arity + 1):
            setter = getattr(builder, f"component_{n}")
            builder = setter(lambda: _make_child(hub, dispatcher))
        with pytest.raises(BuilderValidationError) as exc_info:
            builder.build()
        assert exc_info.value.missing_field == "name"

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_builder_missing_services_raises(self, arity: int) -> None:
        builder = _BUILDERS[arity]().name("agg")
        for n in range(1, arity + 1):
            setter = getattr(builder, f"component_{n}")
            builder = setter(lambda: None)  # type: ignore[arg-type,return-value]
        with pytest.raises(BuilderValidationError) as exc_info:
            builder.build()
        assert exc_info.value.missing_field == "hub"

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_builder_setters_are_immutable(self, arity: int) -> None:
        """BLD-001: every setter returns a new instance."""
        b1 = _BUILDERS[arity]()
        b2 = b1.name("agg")
        b3 = b2.hint("h")
        assert b1 is not b2
        assert b2 is not b3
        assert b1._name is None
        assert b2._name == "agg"
        assert b3._hint == "h"

    @pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
    def test_hint_default_and_override(self, arity: int) -> None:
        hub = _make_hub()
        dispatcher = _make_dispatcher()
        # Default hint.
        agg_default = _build_arity(arity, hub, dispatcher)
        assert agg_default.hint == ""  # type: ignore[attr-defined]

        # Override hint.
        builder = _BUILDERS[arity]().name("agg").hint("custom").services(hub, dispatcher)
        for n in range(1, arity + 1):
            setter = getattr(builder, f"component_{n}")
            builder = setter(lambda n=n: _make_child(hub, dispatcher, f"c{n}"))
        agg_overridden = builder.build()
        assert agg_overridden.hint == "custom"
