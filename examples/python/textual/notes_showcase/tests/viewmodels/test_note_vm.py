"""Tests for NoteVM."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import cast

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import (
    AsyncRelayCommand,
    IClosable,
    IDeletable,
    IReconstructable,
    ISavable,
    ISelectable,
    MessageHub,
    PropertyChangedMessage,
    RxDispatcher,
)
from vmx.capabilities import IExpandable
from vmx.messages.protocols import Message

from notes_showcase.models.note_model import NoteModel
from notes_showcase.viewmodels.note_vm import NoteVM

_T0 = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


def _model(
    *, note_id: str = "note-01", title: str = "Hello", starred: bool = False
) -> NoteModel:
    return NoteModel(
        id=note_id,
        notebook_id="nb-1",
        title=title,
        tags=(),
        body="",
        starred=starred,
        created_at=_T0,
        updated_at=_T0,
    )


def _build(**kwargs: object) -> NoteVM:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    builder = NoteVM.builder().name("note").services(hub, dispatcher).model(_model())
    for k, v in kwargs.items():
        builder = getattr(builder, k)(v)
    return builder.build()


def test_capability_set_is_exactly_the_five_declared_interfaces() -> None:
    vm = _build()
    assert isinstance(vm, ISelectable)
    assert isinstance(vm, IClosable)
    assert isinstance(vm, IDeletable)
    assert isinstance(vm, ISavable)
    assert isinstance(vm, IReconstructable)
    assert not isinstance(vm, IExpandable)


def test_setting_model_emits_title_and_starred_messages_when_changed() -> None:
    vm = _build()
    vm.construct()
    observed: list[str] = []
    vm.hub.messages.subscribe(
        on_next=lambda m: (
            observed.append(cast(PropertyChangedMessage[object], m).property_name)
            if isinstance(m, PropertyChangedMessage)
            else None
        )
    )

    vm.model = _model(title="Updated", starred=True)

    assert "model" in observed
    assert "title" in observed
    assert "starred" in observed


def test_close_command_invokes_on_close_callback() -> None:
    captured: list[NoteVM] = []
    vm = _build(on_close=lambda v: captured.append(v))
    vm.construct()
    vm.close_command.execute()
    assert captured == [vm]


async def test_save_command_invokes_on_save_callback_only_when_constructed() -> None:
    captured: list[NoteVM] = []
    vm = _build(on_save=lambda v: captured.append(v))
    # Pre-construct: can_save False — execute should no-op.
    await vm.save_command.execute_async()
    assert captured == []
    vm.construct()
    await vm.save_command.execute_async()
    assert captured == [vm]


async def test_save_command_awaits_async_callback_and_propagates_failure() -> None:
    release = asyncio.Event()

    async def fail_after_release(_vm: NoteVM) -> None:
        await release.wait()
        raise OSError("disk full")

    vm = _build(on_save=fail_after_release)
    vm.construct()
    assert isinstance(vm.save_command, AsyncRelayCommand)

    execution = asyncio.create_task(vm.save_command.execute_async())
    await asyncio.sleep(0)
    assert vm.save_command.is_executing
    release.set()
    with pytest.raises(OSError, match="disk full"):
        await execution
    assert not vm.save_command.is_executing


async def test_delete_command_invokes_on_delete_callback() -> None:
    captured: list[NoteVM] = []
    vm = _build(on_delete=lambda v: captured.append(v))
    vm.construct()
    assert isinstance(vm.delete_command, AsyncRelayCommand)
    await vm.delete_command.execute_async()
    assert captured == [vm]


def test_delete_rejects_other_note_instance() -> None:
    other = _build()
    captured: list[NoteVM] = []
    vm = _build(on_delete=lambda v: captured.append(v))
    vm.construct()
    other.construct()
    vm.delete(other)
    assert captured == []


def test_dispose_disposes_owned_commands() -> None:
    vm = _build()
    vm.construct()
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED


def test_builder_requires_name_and_model() -> None:
    import pytest

    with pytest.raises(ValueError, match="name"):
        NoteVM.builder().build()
    with pytest.raises(ValueError, match="model"):
        NoteVM.builder().name("x").build()


# ── confirmation-decorator parity: ConfirmationDecoratorCommand parity with C# trio ──
#
# These mirror NotesShowcase.Tests.ViewModels.NoteVMTests
# (DeleteCommand_with_confirm_returning_{false,true}_* + the
# Note-deleted notification on success). Indirect coverage exists via
# test_notes_view_vm.py, but the contract deserves dedicated NoteVM-level
# assertions so a regression in the wrapping logic surfaces here first.


def _build_with_confirm(
    *,
    confirm: bool,
    on_delete: object | None = None,
    notification_hub: object | None = None,
) -> NoteVM:
    """Construct a NoteVM whose DeleteCommand is wrapped in a
    ConfirmationDecoratorCommand returning ``confirm``.
    """
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )

    async def _confirm(_vm: NoteVM) -> bool:
        return confirm

    builder = (
        NoteVM.builder()
        .name("note")
        .services(hub, dispatcher)
        .model(_model())
        .confirm_delete(_confirm)
    )
    if on_delete is not None:
        builder = builder.on_delete(on_delete)  # type: ignore[arg-type]
    if notification_hub is not None:
        builder = builder.notification_hub(notification_hub)  # type: ignore[arg-type]
    vm = builder.build()
    vm.construct()
    return vm


async def test_delete_command_with_confirm_false_does_not_invoke_on_delete() -> None:
    """User clicks 'No' in the confirm dialog → on_delete must NOT fire."""
    from vmx.commands import ConfirmationDecoratorCommand

    captured: list[NoteVM] = []
    vm = _build_with_confirm(confirm=False, on_delete=lambda v: captured.append(v))

    assert isinstance(vm.delete_command, ConfirmationDecoratorCommand)
    await vm.delete_command.execute_async()  # type: ignore[union-attr]

    assert captured == []  # delete rejected by the confirm gate


async def test_delete_command_with_confirm_true_invokes_on_delete() -> None:
    """User clicks 'Yes' in the confirm dialog → on_delete fires with self."""
    from vmx.commands import ConfirmationDecoratorCommand

    captured: list[NoteVM] = []
    vm = _build_with_confirm(confirm=True, on_delete=lambda v: captured.append(v))

    assert isinstance(vm.delete_command, ConfirmationDecoratorCommand)
    await vm.delete_command.execute_async()  # type: ignore[union-attr]
    for _ in range(10):
        if captured:
            break
        await asyncio.sleep(0)

    assert captured == [vm]


async def test_delete_command_with_confirm_true_publishes_note_deleted_notification() -> (
    None
):
    """Successful confirmed delete + a NotificationHub posts 'Note deleted'."""
    from vmx.commands import ConfirmationDecoratorCommand
    from vmx.notifications import NotificationHub

    notification_hub = NotificationHub()
    observed: list[str] = []
    notification_hub.pending.subscribe(
        on_next=lambda snapshot: observed.extend(
            n.message for n in snapshot if n.message not in observed
        )
    )
    vm = _build_with_confirm(
        confirm=True,
        on_delete=lambda _v: None,
        notification_hub=notification_hub,
    )

    assert isinstance(vm.delete_command, ConfirmationDecoratorCommand)
    await vm.delete_command.execute_async()  # type: ignore[union-attr]
    for _ in range(10):
        if observed:
            break
        await asyncio.sleep(0)

    assert any("Note deleted" in msg and "Hello" in msg for msg in observed)


async def test_delete_success_notification_waits_for_async_callback() -> None:
    from vmx.notifications import NotificationHub

    release = asyncio.Event()
    notified = asyncio.Event()

    async def persist(_vm: NoteVM) -> None:
        await release.wait()

    notification_hub = NotificationHub()
    notification_hub.pending.subscribe(
        on_next=lambda snapshot: (
            notified.set()
            if any("Note deleted" in n.message for n in snapshot)
            else None
        )
    )
    vm = _build_with_confirm(
        confirm=True,
        on_delete=persist,
        notification_hub=notification_hub,
    )

    await vm.delete_command.execute_async()  # type: ignore[union-attr]

    assert not notified.is_set()
    release.set()
    await asyncio.wait_for(notified.wait(), timeout=2)


async def test_delete_failure_does_not_publish_success() -> None:
    from vmx.notifications import NotificationHub

    async def fail(_vm: NoteVM) -> None:
        raise OSError("disk full")

    notification_hub = NotificationHub()
    observed: list[str] = []
    notification_hub.pending.subscribe(
        on_next=lambda snapshot: observed.extend(n.message for n in snapshot)
    )
    vm = _build(on_delete=fail, notification_hub=notification_hub)
    vm.construct()
    assert isinstance(vm.delete_command, AsyncRelayCommand)

    with pytest.raises(OSError, match="disk full"):
        await vm.delete_command.execute_async()

    assert not any("Note deleted" in message for message in observed)
