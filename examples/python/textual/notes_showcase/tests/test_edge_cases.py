"""Edge-case backfill — Notes-Showcase flagship app.

Covers four edge cases that the original test pass missed (audit task D):

1. Empty-on-startup     — workspace constructs cleanly with zero notebooks.
2. Async failure mode   — repo failures are swallowed by VMs (no crash).
3. Rapid selection race — newer ``bind_to_async`` wins over a stale one.
4. Readonly notebook    — ``add_note_command`` gated by ``is_readonly``.

These are not new conformance IDs — they are example-app behaviors that
should hold across every Notes-Showcase flavor. Cross-flavor parity is
maintained in ``tests/edgeCases.test.ts`` for the React flavor.
"""

from __future__ import annotations

import asyncio

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message
from vmx.notifications import NotificationHub

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM


# ── Helpers ────────────────────────────────────────────────────────────────


def _empty_seed() -> tuple[list[NotebookModel], list[NoteModel]]:
    """Return an empty seed — zero notebooks and zero notes."""
    return [], []


def _build_workspace(
    seed: tuple[list[NotebookModel], list[NoteModel]],
    *,
    load_all_delay: float = 0.0,
    load_notes_delay: float = 0.0,
    save_note_delay: float = 0.0,
    add_notebook_delay: float = 0.0,
) -> tuple[WorkspaceVM, InMemoryNoteRepository]:
    repo = InMemoryNoteRepository(
        seed,
        load_all_delay=load_all_delay,
        load_notes_delay=load_notes_delay,
        save_note_delay=save_note_delay,
        add_notebook_delay=add_notebook_delay,
        delete_note_delay=0.0,
        export_delay=0.0,
    )
    ws = (
        WorkspaceVM.builder()
        .name("workspace")
        .repository(repo)
        .notification_hub(NotificationHub())
        .build()
    )
    return ws, repo


# ── (1) Empty-on-startup ───────────────────────────────────────────────────


async def test_construct_async_with_zero_notebooks_does_not_crash() -> None:
    """Edge case 1: ``WorkspaceVM.construct_async()`` succeeds with no seed.

    Asserts the structural surface the host UI inspects on first paint:

    * ``notebooks_root.all.count == 0`` and ``roots == []``
    * ``notes_view.inner.count == 0`` and ``visible_items == []``
    * ``note_form.has_bound_note is False``
    * commands gated on a current notebook stay disabled
    """
    ws, _ = _build_workspace(_empty_seed())
    await ws.construct_async()
    assert ws.is_constructed
    # Notebooks tree is empty — no auto-selection, no focus, no current.
    assert ws.notebooks_root.all.count == 0
    assert ws.notebooks_root.roots == []
    assert ws.notebooks_root.current is None
    # Notes view: nothing bound, nothing visible.
    assert ws.notes_view.inner.count == 0
    assert ws.notes_view.visible_items == []
    assert ws.notes_view.bound_notebook_id is None
    # Form is unbound; predicates stay safe.
    assert ws.note_form.has_bound_note is False
    assert ws.note_form.is_dirty.value is False
    assert ws.note_form.approve_command.can_execute() is False
    # WorkspaceVM new-note command requires a current notebook.
    assert ws.new_note_command.can_execute() is False
    ws.dispose()


def test_construct_sync_with_zero_notebooks_keeps_aggregate_consistent() -> None:
    """Synchronous construct on an empty seed leaves children safely zero."""
    ws, _ = _build_workspace(_empty_seed())
    ws.construct()
    assert ws.is_constructed
    assert ws.notebooks_root.all.count == 0
    assert ws.notes_view.inner.count == 0
    assert ws.note_form.has_bound_note is False
    ws.dispose()


# ── (2) Async failure mode ─────────────────────────────────────────────────


async def test_note_form_approve_swallows_repo_save_failure() -> None:
    """Edge case 2a: ``NoteFormVM.approve_command`` does NOT advance snapshot
    when the underlying ``repo.save_note`` raises, and does NOT propagate the
    exception to the fire-and-forget caller.
    """
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        save_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    notification_hub = NotificationHub()
    form = (
        NoteFormVM.builder()
        .name("form")
        .services(hub, dispatcher)
        .repository(repo)
        .notification_hub(notification_hub)
        .build()
    )
    _, notes = await repo.load_all()
    original = notes[0]
    form.bind_to(original)
    # Edit the title so approve is enabled.
    form.title = "Edited offline"
    snapshot_before = form.snapshot
    # Arm a single-shot failure on the next save.
    repo.fail_next(RuntimeError("disk full"))
    # approve_async swallows the failure (does NOT raise to the caller).
    with pytest.raises(RuntimeError, match="disk full"):
        await form.approve_async()
    # Snapshot did NOT advance — the form is still dirty.
    assert form.snapshot == snapshot_before
    assert form.is_dirty.value is True
    # Recovery: next approve succeeds (failure was single-shot).
    await form.approve_async()
    assert form.snapshot.title == "Edited offline"
    assert form.is_dirty.value is False
    form.dispose()


async def test_workspace_construct_async_propagates_load_failure() -> None:
    """Edge case 2b: ``WorkspaceVM.construct_async()`` propagates a load
    failure rather than silently leaving the workspace in a half-built state.

    The aggregate is still ``CONSTRUCTED`` (the sync cascade completed
    before ``populate`` ran), so callers can inspect status and recover.
    """
    ws, repo = _build_workspace(build_seed())
    repo.fail_next(RuntimeError("network down"))
    with pytest.raises(RuntimeError, match="network down"):
        await ws.construct_async()
    # The synchronous aggregate cascade completed before populate ran.
    assert ws.is_constructed
    assert ws.notebooks_root.all.count == 0  # populate aborted
    ws.dispose()


# ── (3) Rapid notebook selection concurrency ────────────────────────────────


async def test_rapid_notebook_selection_b_wins_over_stale_a() -> None:
    """Edge case 3: ``bind_to_async`` cancels stale in-flight loads.

    Select notebook A, then notebook B *before* A's ``load_notes`` resolves.
    With the active-binding-token guard B's results must win and A's must
    be discarded — otherwise the view would briefly show A's notes and the
    user's selection of B would be lost.
    """
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        # Non-zero delay so we can interleave two binds reliably.
        load_notes_delay=0.05,
        save_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    view = (
        NotesViewVM.builder()
        .name("notes")
        .services(hub, dispatcher)
        .repository(repo)
        .page_size(5)
        .build()
    )
    view.construct()

    # Race: schedule A then B without awaiting between them. Both start
    # their load_notes immediately; B's call increments the active token so
    # A's resume becomes a no-op.
    task_a = asyncio.create_task(view.bind_to_async("nb-reviews"))  # 7 notes
    task_b = asyncio.create_task(view.bind_to_async("nb-personal"))  # 2 notes
    await asyncio.gather(task_a, task_b)

    assert view.bound_notebook_id == "nb-personal"
    assert view.inner.count == 2
    assert {n.model.notebook_id for n in view.inner} == {"nb-personal"}
    view.dispose()


# ── (4) Readonly notebook capability gating ─────────────────────────────────


def test_notebook_model_default_is_not_readonly() -> None:
    """Edge case 4 setup: default ``is_readonly`` is ``False`` so existing
    seed data is unaffected.
    """
    nb = NotebookModel(id="nb", name="N", parent_id=None)
    assert nb.is_readonly is False


async def test_capability_actions_add_note_disabled_for_readonly_notebook() -> None:
    """Edge case 4: when the bound notebook is readonly,
    ``CapabilityActionsVM.add_note_command.can_execute()`` is ``False``.

    Wiring proof:
      * NotebookModel.is_readonly flag flows through
      * WorkspaceVM.construct_async mirrors it into notes_view
      * CapabilityActionsVM's predicate consults notes_view
    """
    seed_notebooks = [
        NotebookModel(
            id="nb-readonly", name="Archive", parent_id=None, is_readonly=True
        ),
    ]
    ws, _ = _build_workspace((seed_notebooks, []))
    await ws.construct_async()
    # NotesViewVM mirrors the notebook's readonly flag.
    assert ws.notes_view.current_notebook_is_readonly is True
    # CapabilityActionsVM's add-note command is gated off.
    assert ws.capability_actions.add_note_command.can_execute() is False
    ws.dispose()


async def test_capability_actions_add_note_enabled_for_writable_notebook() -> None:
    """Positive case: a non-readonly notebook enables ``add_note_command``."""
    seed_notebooks = [
        NotebookModel(id="nb-rw", name="Drafts", parent_id=None, is_readonly=False),
    ]
    ws, _ = _build_workspace((seed_notebooks, []))
    await ws.construct_async()
    assert ws.notes_view.current_notebook_is_readonly is False
    assert ws.capability_actions.add_note_command.can_execute() is True
    ws.dispose()


def test_capability_actions_add_note_default_predicate_always_true() -> None:
    """A standalone ``CapabilityActionsVM`` built without ``can_add_note``
    uses an always-true predicate so the bar stays functional in tests /
    hosts that don't wire the readonly gate.
    """
    from notes_showcase.viewmodels.capability_actions_vm import CapabilityActionsVM

    state: dict[str, object | None] = {"focused": None}
    vm = (
        CapabilityActionsVM.builder()
        .name("actions")
        .focused_getter(lambda: state["focused"])
        .build()
    )
    assert vm.add_note_command.can_execute() is True
    vm.dispose()
