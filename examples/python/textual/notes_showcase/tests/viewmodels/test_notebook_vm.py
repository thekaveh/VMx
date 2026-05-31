"""Tests for NotebookVM."""

from __future__ import annotations

from typing import cast

from reactivex.scheduler import ImmediateScheduler

from vmx import (
    ICollapsible,
    IExpandable,
    IExpansionTogglable,
    IReconstructable,
    ISelectable,
    MessageHub,
    PropertyChangedMessage,
    RxDispatcher,
)
from vmx.capabilities import IClosable, INewCreatable
from vmx.messages.protocols import Message

from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.viewmodels.notebook_vm import NotebookVM


def _build(
    *,
    notebook_id: str = "nb-1",
    name: str = "Work",
    initially_expanded: bool = False,
) -> NotebookVM:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(),
        background=ImmediateScheduler(),
    )
    return (
        NotebookVM.builder()
        .name("nb")
        .services(hub, dispatcher)
        .model(NotebookModel(id=notebook_id, name=name, parent_id=None))
        .initially_expanded(initially_expanded)
        .build()
    )


def test_capability_set_is_exactly_the_five_declared_interfaces() -> None:
    vm = _build()
    assert isinstance(vm, ISelectable)
    assert isinstance(vm, IExpandable)
    assert isinstance(vm, ICollapsible)
    assert isinstance(vm, IExpansionTogglable)
    assert isinstance(vm, IReconstructable)
    assert not isinstance(vm, IClosable)
    assert not isinstance(vm, INewCreatable)


def test_toggle_expansion_emits_is_expanded_property_changed_message() -> None:
    vm = _build()
    vm.construct()
    observed: list[str] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: observed.append(
            cast(PropertyChangedMessage[object], m).property_name
        )
        if isinstance(m, PropertyChangedMessage)
        else None
    )

    vm.toggle_expansion()

    assert "is_expanded" in observed
    assert vm.is_expanded is True


def test_setting_model_emits_model_and_notebook_name_messages() -> None:
    vm = _build(name="Old Name")
    vm.construct()
    observed: list[str] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: observed.append(
            cast(PropertyChangedMessage[object], m).property_name
        )
        if isinstance(m, PropertyChangedMessage)
        else None
    )

    vm.model = NotebookModel(
        id=vm.model.id, name="New Name", parent_id=vm.model.parent_id
    )

    assert "model" in observed
    assert "notebook_name" in observed
    assert vm.notebook_name == "New Name"


def test_setting_model_to_equal_value_is_no_op() -> None:
    vm = _build(name="Same")
    vm.construct()
    observed: list[str] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: observed.append(
            cast(PropertyChangedMessage[object], m).property_name
        )
        if isinstance(m, PropertyChangedMessage)
        else None
    )

    vm.model = vm.model

    assert "model" not in observed


def test_expand_and_collapse_predicates_track_state() -> None:
    vm = _build(initially_expanded=False)
    vm.construct()
    assert vm.can_expand()
    assert not vm.can_collapse()
    vm.expand()
    assert vm.is_expanded
    assert not vm.can_expand()
    assert vm.can_collapse()
    vm.collapse()
    assert not vm.is_expanded
    # Idempotent re-collapse.
    vm.collapse()
    assert not vm.is_expanded


def test_dispose_disposes_expandable_state() -> None:
    vm = _build()
    vm.construct()
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED


def test_builder_requires_name_and_model() -> None:
    import pytest

    with pytest.raises(ValueError, match="name"):
        NotebookVM.builder().build()
    with pytest.raises(ValueError, match="model"):
        NotebookVM.builder().name("x").build()


# ── Phase 5.b binding-gap #2: children accessor ─────────────────────────────


def test_children_is_empty_when_no_getter_supplied() -> None:
    vm = _build()
    assert vm.children == []


def test_children_getter_late_bind_returns_supplied_list() -> None:
    parent = _build(notebook_id="nb-parent")
    child_a = _build(notebook_id="nb-a")
    child_b = _build(notebook_id="nb-b")
    parent.set_children_getter(lambda _: [child_a, child_b])
    assert parent.children == [child_a, child_b]


def test_children_getter_via_builder() -> None:
    child = _build(notebook_id="nb-c")
    vm = (
        NotebookVM.builder()
        .name("parent")
        .services(MessageHub[Message](), RxDispatcher.immediate())
        .model(NotebookModel(id="nb-parent", name="P", parent_id=None))
        .children_getter(lambda _: [child])
        .build()
    )
    assert vm.children == [child]
