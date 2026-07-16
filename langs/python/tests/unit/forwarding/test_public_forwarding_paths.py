"""Public-API integration coverage for the two forwarding facades."""

from __future__ import annotations

import pytest

from vmx import (
    ComponentVM,
    ComponentVMOf,
    CompositeVM,
    ConstructionStatus,
    ForwardingComponentVM,
    ForwardingCompositeVM,
    MessageHub,
    RxDispatcher,
    StatusTransitionError,
)


def _leaf(name: str) -> ComponentVM:
    return ComponentVM.builder().name(name).with_null_services().build()


def test_component_facade_exercises_real_lifecycle_selection_streams_and_disposal() -> None:
    child = (
        ComponentVMOf[str]
        .builder()
        .name("child")
        .model("initial")
        .modeled_hinter(lambda model: f"hint:{model}")
        .with_null_services()
        .build()
    )
    parent: CompositeVM[ComponentVMOf[str]] = (
        CompositeVM[ComponentVMOf[str]]
        .builder()
        .name("parent")
        .children(lambda: [child])
        .services(MessageHub(), RxDispatcher.immediate())
        .build()
    )
    facade = ForwardingComponentVM(child)
    properties: list[str] = []
    completed: list[bool] = []
    facade.property_changed.subscribe(
        properties.append,
        on_completed=lambda: completed.append(True),
    )

    assert (facade.name, facade.hint, facade.type) == (child.name, child.hint, child.type)
    assert facade.hub is child.hub
    assert facade.model == "initial"
    assert facade.modeled_hint == "hint:initial"
    assert facade.select_command is child.select_command
    assert facade.deselect_command is child.deselect_command
    assert facade.select_next_command is child.select_next_command
    assert facade.select_previous_command is child.select_previous_command
    assert facade.reconstruct_command is child.reconstruct_command

    facade.model = "changed"
    facade.republish_model()
    assert facade.model == "changed"
    assert properties.count("model") == 2

    assert facade.can_construct() is True
    parent.construct()
    assert facade.status is ConstructionStatus.CONSTRUCTED
    assert facade.is_constructed is True
    assert facade.can_reconstruct() is True
    facade.reconstruct()
    assert facade.status is ConstructionStatus.CONSTRUCTED
    assert facade.can_destruct() is True
    facade.destruct()
    assert facade.status is ConstructionStatus.DESTRUCTED
    facade.construct()

    assert facade.is_current is False
    assert facade.can_select() is True
    facade.select()
    assert parent.current is child
    assert facade.is_current is True
    assert facade.can_deselect() is True
    facade.deselect()
    assert parent.current is None

    facade.dispose()
    assert facade.status is ConstructionStatus.DISPOSED
    assert completed == [True]
    with pytest.raises(StatusTransitionError):
        facade.construct()
    parent.dispose()


def test_composite_facade_exercises_real_selection_collection_and_exception_paths() -> None:
    a, b, c = _leaf("a"), _leaf("b"), _leaf("c")
    wrapped: CompositeVM[ComponentVM] = (
        CompositeVM[ComponentVM]
        .builder()
        .name("wrapped")
        .children(lambda: [a, b, c])
        .services(MessageHub(), RxDispatcher.immediate())
        .build()
    )
    facade = ForwardingCompositeVM(wrapped)
    collection_actions: list[str] = []
    property_names: list[str] = []
    collection_completed: list[bool] = []
    property_completed: list[bool] = []
    facade.on_collection_changed.subscribe(
        lambda event: collection_actions.append(event.action),
        on_completed=lambda: collection_completed.append(True),
    )
    facade.property_changed.subscribe(
        property_names.append,
        on_completed=lambda: property_completed.append(True),
    )
    facade.construct()

    assert (facade.name, facade.hint, facade.type) == (
        wrapped.name,
        wrapped.hint,
        wrapped.type,
    )
    assert facade.hub is wrapped.hub
    assert facade.count == len(facade) == 3
    assert list(facade) == [a, b, c]
    assert facade[1] is b
    assert b in facade
    assert facade.index_of(b) == 1
    assert facade.index_of(_leaf("missing")) == -1
    assert facade.select_command is wrapped.select_command
    assert facade.deselect_command is wrapped.deselect_command
    assert facade.select_next_command is wrapped.select_next_command
    assert facade.select_previous_command is wrapped.select_previous_command
    assert facade.reconstruct_command is wrapped.reconstruct_command

    assert facade.is_current is False
    assert facade.is_constructed is True
    assert facade.can_reconstruct() is True
    facade.reconstruct()
    assert facade.can_destruct() is True
    facade.destruct()
    assert facade.can_construct() is True
    facade.construct()
    assert facade.can_select() is False
    facade.select()
    assert facade.can_deselect() is False
    facade.deselect()
    assert facade.can_select_component(a) is True
    facade.select_component(a)
    assert facade.current is a
    assert "current" in property_names
    facade.deselect_component(a)
    assert facade.current is None
    facade.current = b
    assert facade.current is b

    replacement = _leaf("replacement")
    inserted = _leaf("inserted")
    added = _leaf("added")
    facade[1] = replacement
    facade.insert(1, inserted)
    facade.add(added)
    facade.move(0, len(facade) - 1)
    assert facade.remove(inserted) is True
    facade.remove_at(0)
    with facade.batch_update():
        facade.add(_leaf("batch-a"))
        facade.add(_leaf("batch-b"))
    assert "add" in collection_actions
    assert "remove" in collection_actions
    assert "move" in collection_actions
    assert "reset" in collection_actions

    with pytest.raises(IndexError):
        _ = facade[99]
    with pytest.raises(IndexError):
        facade.move(0, len(facade))

    facade.clear()
    assert facade.count == 0
    facade.dispose()
    assert facade.status is ConstructionStatus.DISPOSED
    assert collection_completed == [True]
    assert property_completed == [True]
    with pytest.raises(StatusTransitionError):
        facade.reconstruct()
