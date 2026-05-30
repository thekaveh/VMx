"""Tests for NoteVM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from reactivex.scheduler import ImmediateScheduler

from vmx import (
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
        on_next=lambda m: observed.append(cast(PropertyChangedMessage[object], m).property_name)
        if isinstance(m, PropertyChangedMessage)
        else None
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


def test_save_command_invokes_on_save_callback_only_when_constructed() -> None:
    captured: list[NoteVM] = []
    vm = _build(on_save=lambda v: captured.append(v))
    # Pre-construct: can_save False — execute should no-op.
    vm.save_command.execute()
    assert captured == []
    vm.construct()
    vm.save_command.execute()
    assert captured == [vm]


def test_delete_command_invokes_on_delete_callback() -> None:
    captured: list[NoteVM] = []
    vm = _build(on_delete=lambda v: captured.append(v))
    vm.construct()
    vm.delete_command.execute()
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
