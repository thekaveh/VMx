"""Tests for NotesViewVM."""

from __future__ import annotations

import pytest
from reactivex.scheduler import ImmediateScheduler
from reactivex.testing import TestScheduler

from vmx import (
    Filterable,
    IReconstructable,
    ISearchable,
    MessageHub,
    Pageable,
    RxDispatcher,
)
from vmx.messages.protocols import Message

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.note_vm import NoteVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM


def _build(
    *,
    page_size: int = 5,
    debounce: float = 0.0,
    scheduler: object | None = None,
) -> NotesViewVM:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    builder = (
        NotesViewVM.builder()
        .name("notes")
        .services(hub, dispatcher)
        .repository(repo)
        .page_size(page_size)
        .search_debounce_seconds(debounce)
    )
    if scheduler is not None:
        builder = builder.search_scheduler(scheduler)  # type: ignore[arg-type]
    return builder.build()


def test_capability_set_is_pageable_filterable_searchable_reconstructable() -> None:
    vm = _build()
    assert isinstance(vm, Pageable)
    assert isinstance(vm, Filterable)
    assert isinstance(vm, ISearchable)
    assert isinstance(vm, IReconstructable)


async def test_bind_to_async_loads_notes_for_notebook() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    assert vm.bound_notebook_id == "nb-reviews"
    assert vm.inner.count == 7
    assert vm.visible_items[0].model.notebook_id == "nb-reviews"


async def test_show_starred_only_filters_to_starred_notes() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    starred_ids = {n.model.id for n in vm.filtered_items if n.model.starred}
    assert {"note-02", "note-07"}.issubset(starred_ids)
    vm.show_starred_only = True
    assert all(n.model.starred for n in vm.filtered_items)
    assert {n.model.id for n in vm.filtered_items} == {"note-02", "note-07"}


async def test_filter_predicate_narrows_visible_items() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    vm.filter = lambda n: "Auth" in n.model.title
    assert {n.model.id for n in vm.filtered_items} == {"note-02"}
    vm.filter = None
    assert len(vm.filtered_items) == 7


async def test_pagination_boundaries_are_no_ops_at_edges() -> None:
    vm = _build(page_size=3)
    vm.construct()
    await vm.bind_to_async("nb-reviews")  # 7 notes → 3 pages (3/3/1)
    assert vm.page_count == 3
    assert vm.current_page_index == 0
    assert vm.move_to_first_page_command.can_execute() is False
    assert vm.move_to_previous_page_command.can_execute() is False
    assert vm.move_to_next_page_command.can_execute() is True
    assert vm.move_to_last_page_command.can_execute() is True
    vm.move_to_previous_page()
    assert vm.current_page_index == 0  # no-op at first page
    vm.move_to_last_page()
    assert vm.current_page_index == 2
    assert vm.move_to_first_page_command.can_execute() is True
    assert vm.move_to_previous_page_command.can_execute() is True
    assert vm.move_to_next_page_command.can_execute() is False
    assert vm.move_to_last_page_command.can_execute() is False
    vm.move_to_next_page()
    assert vm.current_page_index == 2  # no-op at last page
    vm.move_to_first_page()
    assert vm.current_page_index == 0


async def test_bind_to_swaps_inner_items() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    assert vm.inner.count == 7
    await vm.bind_to_async("nb-personal")
    assert vm.inner.count == 2
    assert {n.model.id for n in vm.inner} == {"note-11", "note-12"}


async def test_is_empty_derived_property_tracks_filtered_count() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-archive")
    assert vm.is_empty.value is True
    await vm.bind_to_async("nb-personal")
    assert vm.is_empty.value is False


async def test_page_label_derived_property_updates_with_page_changes() -> None:
    vm = _build(page_size=2)
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    assert vm.page_label.value == "Page 1 of 4"
    vm.move_to_next_page()
    assert vm.page_label.value == "Page 2 of 4"


async def test_paging_commands_invoke_underlying_methods() -> None:
    vm = _build(page_size=2)
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    vm.move_to_next_page_command.execute()
    assert vm.current_page_index == 1
    vm.move_to_last_page_command.execute()
    assert vm.current_page_index == vm.page_count - 1
    vm.move_to_previous_page_command.execute()
    assert vm.current_page_index == vm.page_count - 2
    vm.move_to_first_page_command.execute()
    assert vm.current_page_index == 0


async def test_search_term_with_zero_debounce_filters_immediately() -> None:
    vm = _build(debounce=0.0)
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    vm.search_term = "auth"
    assert {n.model.id for n in vm.filtered_items} == {"note-02"}


async def test_search_uses_test_scheduler_for_deterministic_debounce() -> None:
    scheduler = TestScheduler()
    vm = _build(debounce=0.150, scheduler=scheduler)
    vm.construct()
    await vm.bind_to_async("nb-reviews")
    # Set the search term; debounce hasn't elapsed yet.
    vm.search_term = "auth"
    # Before debounce elapses, filtered is unchanged (all 7).
    assert len(vm.filtered_items) == 7
    # Advance virtual time past the debounce window.
    scheduler.advance_by(scheduler.to_seconds(0.2))
    assert {n.model.id for n in vm.filtered_items} == {"note-02"}


def test_builder_requires_name_and_repository() -> None:
    with pytest.raises(ValueError, match="name"):
        NotesViewVM.builder().build()
    with pytest.raises(ValueError, match="repository"):
        NotesViewVM.builder().name("x").build()


async def test_current_setter_emits_property_changed() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-personal")
    first = vm.inner[0]
    vm.current = first
    assert vm.current is first
    vm.current = None
    assert vm.current is None


async def test_close_command_on_note_clears_current_via_on_close_hook() -> None:
    vm = _build()
    vm.construct()
    await vm.bind_to_async("nb-personal")
    first = vm.inner[0]
    assert isinstance(first, NoteVM)
    vm.current = first
    first.close_command.execute()
    assert vm.current is None


def test_dispose_releases_resources() -> None:
    vm = _build()
    vm.construct()
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED


# ── Audit pass #1, B1/B2 symmetric coverage: delete-with-confirm wiring ───


class _AcceptDialog:
    """IDialogService stub that auto-accepts confirms."""

    async def pick_file_to_open(self, filter=None, title=None) -> str | None:  # noqa: ARG002
        return None

    async def pick_file_to_save(
        self, filter=None, title=None, suggested_name=None
    ) -> str | None:  # noqa: ARG002
        return None

    async def confirm(self, message: str, title=None) -> bool:  # noqa: ARG002
        return True

    async def notify(self, message, title=None, severity=None) -> None:  # noqa: ARG002
        return None


async def test_delete_via_dialog_removes_note_and_posts_notification(tmp_path) -> None:  # noqa: ARG001
    """When ``dialog_service`` + ``notification_hub`` are wired, a confirmed
    delete on a NoteVM removes it from the inner collection and posts a
    "Note deleted" notification.
    """
    import asyncio
    from vmx.notifications import Notification, NotificationHub

    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
        delete_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    notification_hub = NotificationHub()
    observed: list[Notification] = []
    notification_hub.pending.subscribe(
        on_next=lambda snap: [observed.append(n) for n in snap if n not in observed]
    )
    vm = (
        NotesViewVM.builder()
        .name("notes")
        .services(hub, dispatcher)
        .repository(repo)
        .dialog_service(_AcceptDialog())
        .notification_hub(notification_hub)
        .build()
    )
    vm.construct()
    await vm.bind_to_async("nb-personal")
    before = vm.inner.count
    target = vm.inner[0]

    # Execute the decorated delete command — confirm returns True → delete fires.
    target.delete_command.execute()
    # Let the confirm coroutine + scheduled remove coroutine run.
    await asyncio.sleep(0.05)

    assert vm.inner.count == before - 1
    assert any("Note deleted" in n.message for n in observed)


async def test_capability_save_persists_the_focused_note() -> None:
    """The capability-bar Save action (``NoteVM.save_command``) persists the
    note's current model through the repo.

    Regression guard: Python previously omitted the ``.on_save`` wiring on the
    per-note builder, so ``NoteVM.save()`` early-returned and the action-bar
    Save was a silent no-op — while C#/TS/Swift all wired it (real-wiring
    audit). The existing capability-actions test only asserted the "Save"
    label was present, not that pressing it persisted.
    """
    import asyncio
    from dataclasses import replace

    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    vm = (
        NotesViewVM.builder()
        .name("notes")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )
    vm.construct()
    await vm.bind_to_async("nb-personal")
    target = vm.inner[0]
    original = target.model
    target.model = replace(original, title="Saved by capability bar")

    target.save_command.execute()
    await asyncio.sleep(0.05)  # drain the fire-and-forget save

    persisted = await repo.load_notes(original.notebook_id)
    assert any(
        n.id == original.id and n.title == "Saved by capability bar" for n in persisted
    )


async def test_repository_search_notes_returns_token_pages_over_all_notes() -> None:
    repo = InMemoryNoteRepository(build_seed(), load_notes_delay=0.0)

    first = await repo.search_notes("review", token=None, page_size=2)

    assert len(first[0]) == 2
    assert first[1] == "2"
    assert all(
        "review" in f"{n.title} {n.body} {' '.join(n.tags)}".lower() for n in first[0]
    )

    second = await repo.search_notes("review", token=first[1], page_size=2)
    assert len(second[0]) > 0
    assert second[0][0].id != first[0][0].id


async def test_global_search_vm_refreshes_resets_terms_and_loads_more() -> None:
    from notes_showcase.viewmodels.global_search_vm import GlobalSearchVM

    repo = InMemoryNoteRepository(build_seed(), load_notes_delay=0.0)
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    vm = (
        GlobalSearchVM.builder()
        .name("global-search")
        .services(hub, dispatcher)
        .repository(repo)
        .page_size(2)
        .search_debounce_seconds(0.0)
        .build()
    )

    vm.search_term = "review"
    await vm.refresh_command.execute_async()
    assert len(vm.results) == 2
    assert vm.has_more is True

    await vm.load_more_command.execute_async()
    assert len(vm.results) > 2

    vm.search_term = "travel"
    await vm.refresh_command.execute_async()
    assert all(n.model.notebook_id == "nb-personal" for n in vm.results)
    vm.dispose()
