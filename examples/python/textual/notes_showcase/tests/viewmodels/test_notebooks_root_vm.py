"""Tests for NotebooksRootVM."""

from __future__ import annotations

from typing import cast

from reactivex.scheduler import ImmediateScheduler

from vmx import (
    INewCreatable,
    IReconstructable,
    MessageHub,
    PropertyChangedMessage,
    RxDispatcher,
    TreeStructureChange,
    TreeStructureChangedMessage,
)
from vmx.messages.protocols import Message

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM


def _build() -> NotebooksRootVM:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        add_notebook_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    return (
        NotebooksRootVM.builder()
        .name("notebooks")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )


def test_capability_set_is_inewcreatable_and_ireconstructable() -> None:
    vm = _build()
    assert isinstance(vm, INewCreatable)
    assert isinstance(vm, IReconstructable)


async def test_populate_loads_seed_notebooks_and_roots_excludes_nested() -> None:
    vm = _build()
    vm.construct()
    await vm.populate()
    assert {nb.model.id for nb in vm.all} == {
        "nb-work",
        "nb-specs",
        "nb-reviews",
        "nb-personal",
        "nb-archive",
    }
    # nb-specs has parent_id nb-work → not in roots
    assert {nb.model.id for nb in vm.roots} == {
        "nb-work",
        "nb-reviews",
        "nb-personal",
        "nb-archive",
    }


async def test_children_of_returns_nested_notebooks() -> None:
    vm = _build()
    vm.construct()
    await vm.populate()
    work = next(nb for nb in vm.all if nb.model.id == "nb-work")
    children = vm.children_of(work)
    assert [c.model.id for c in children] == ["nb-specs"]


async def test_add_notebook_emits_tree_structure_changed_message() -> None:
    vm = _build()
    vm.construct()
    await vm.populate()
    events: list[TreeStructureChangedMessage] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: events.append(cast(TreeStructureChangedMessage, m))
        if isinstance(m, TreeStructureChangedMessage)
        else None
    )

    new_vm = await vm.add_notebook(parent_id=None, name="Side project")

    assert any(
        e.change == TreeStructureChange.ADDED and e.affected is new_vm for e in events
    )
    assert new_vm in list(vm.all)


async def test_current_setter_is_two_way_and_emits_property_changed() -> None:
    vm = _build()
    vm.construct()
    await vm.populate()
    observed: list[str] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: observed.append(
            cast(PropertyChangedMessage[object], m).property_name
        )
        if isinstance(m, PropertyChangedMessage)
        else None
    )

    first = vm.roots[0]
    vm.current = first
    assert vm.current is first
    assert "current" in observed

    # Setting the same again is a no-op.
    observed.clear()
    vm.current = first
    assert "current" not in observed

    # Clearing to None.
    vm.current = None
    assert vm.current is None


def test_can_create_new_requires_constructed_status() -> None:
    vm = _build()
    assert not vm.can_create_new()
    vm.construct()
    assert vm.can_create_new()


async def test_populate_replaces_existing_collection_on_reload() -> None:
    vm = _build()
    vm.construct()
    await vm.populate()
    n1 = vm.all.count
    await vm.populate()  # second populate — counts must match, instances disposed.
    assert vm.all.count == n1


def test_builder_requires_name_and_repository() -> None:
    import pytest

    with pytest.raises(ValueError, match="name"):
        NotebooksRootVM.builder().build()
    with pytest.raises(ValueError, match="repository"):
        NotebooksRootVM.builder().name("x").build()
