"""Unit tests for CompositeVMOf (modeled composite).

Tests cover:
- children populated from model factory + mapper
- count matches number of models
- model mapping correctness
- builder validation
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMOfBuilder
from vmx.components.component_vm import ComponentVMOf
from vmx.composites.builders import CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVMOf
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


class _Model:
    def __init__(self, id_: int) -> None:
        self.id = id_


def _make_child_vm(model: _Model, hub: object, dispatcher: object) -> ComponentVMOf[_Model]:
    return (
        ComponentVMOfBuilder()
        .name(f"child-{model.id}")
        .model(model)
        .services(hub, dispatcher)  # type: ignore[arg-type]
        .build()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_modeled_composite_populates_children_from_models() -> None:
    """Children come from model factory mapped via child_model_to_child_vm."""
    hub = _hub()
    disp = _dispatcher()
    m1 = _Model(1)
    m2 = _Model(2)

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: [m1, m2])
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .build()
    )

    comp.construct()

    assert comp.count == 2
    assert comp[0].model is m1
    assert comp[1].model is m2


def test_modeled_composite_children_are_constructed() -> None:
    hub = _hub()
    disp = _dispatcher()
    models = [_Model(i) for i in range(3)]

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: list(models))
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .build()
    )

    comp.construct()

    assert all(c.status == ConstructionStatus.CONSTRUCTED for c in comp)


def test_modeled_composite_builder_missing_children_models_raises() -> None:
    from vmx.builders.exceptions import BuilderValidationError

    hub = _hub()
    disp = _dispatcher()
    with pytest.raises(BuilderValidationError):
        (
            CompositeVMOfBuilder()
            .name("x")
            .services(hub, disp)
            .child_model_to_child_view_model(lambda m: m)
            .build()
        )


def test_modeled_composite_builder_missing_mapper_raises() -> None:
    from vmx.builders.exceptions import BuilderValidationError

    hub = _hub()
    disp = _dispatcher()
    with pytest.raises(BuilderValidationError):
        (CompositeVMOfBuilder().name("x").services(hub, disp).children_models(lambda: []).build())


def test_modeled_composite_builder_name_returns_new_instance() -> None:
    b1 = CompositeVMOfBuilder()
    b2 = b1.name("y")
    assert b1 is not b2
    assert b1._name is None
    assert b2._name == "y"


# ---------------------------------------------------------------------------
# Builder declarative hook — current(selector) on the modeled builder
# spec/06 §3.X, ADR-0042 (COMP-025)
# ---------------------------------------------------------------------------


def test_modeled_current_selector_drives_initial_selection_after_construct() -> None:
    """current(selector) picks the initial Current after children Constructed."""
    hub = _hub()
    disp = _dispatcher()
    models = [_Model(i) for i in range(3)]

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: list(models))
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .current(lambda xs: list(xs)[1])
        .build()
    )

    comp.construct()

    assert comp.current is comp[1]


def test_modeled_current_selector_returning_none_leaves_current_none() -> None:
    """current(selector) returning None leaves Current at its prior value (None)."""
    hub = _hub()
    disp = _dispatcher()

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: [_Model(1)])
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .current(lambda _: None)
        .build()
    )

    comp.construct()

    assert comp.current is None


# ---------------------------------------------------------------------------
# Builder declarative hook — on_current_changed(callback) on the modeled builder
# spec/06 §3.X, ADR-0042 (COMP-026)
# ---------------------------------------------------------------------------


def test_modeled_on_current_changed_fires_after_each_change() -> None:
    """on_current_changed(callback) fires after every Current transition."""
    hub = _hub()
    disp = _dispatcher()
    models = [_Model(1), _Model(2)]
    observed: list[ComponentVMOf[_Model] | None] = []

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: list(models))
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .on_current_changed(observed.append)
        .build()
    )
    comp.construct()
    comp.select_component(comp[1])
    comp.deselect_component(comp[1])

    assert observed == [comp[1], None]


def test_modeled_composite_destruct_clears_current() -> None:
    hub = _hub()
    disp = _dispatcher()
    m1 = _Model(1)

    comp: CompositeVMOf[_Model, ComponentVMOf[_Model]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: [m1])
        .child_model_to_child_view_model(lambda m: _make_child_vm(m, hub, disp))
        .build()
    )
    comp.construct()
    comp.current = comp[0]

    comp.destruct()

    assert comp.current is None
    assert comp.status == ConstructionStatus.DESTRUCTED
