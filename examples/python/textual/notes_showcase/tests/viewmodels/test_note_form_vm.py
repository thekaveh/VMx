"""Tests for NoteFormVM."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import (
    IReconstructable,
    MessageHub,
    RxDispatcher,
)
from vmx.messages.protocols import Message
from vmx.notifications import NotificationHub

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.note_form_vm import NoteFormVM


def _build_vm(*, with_notification_hub: bool = False) -> tuple[NoteFormVM, NotificationHub | None]:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        save_note_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    builder = (
        NoteFormVM.builder()
        .name("form")
        .services(hub, dispatcher)
        .repository(repo)
    )
    notification_hub: NotificationHub | None = None
    if with_notification_hub:
        notification_hub = NotificationHub()
        builder = builder.notification_hub(notification_hub)
    return builder.build(), notification_hub


def _sample_note(title: str = "Hello") -> NoteModel:
    return NoteModel(
        id="note-x",
        notebook_id="nb-1",
        title=title,
        tags=("alpha",),
        body="body",
        starred=False,
        created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )


def test_capability_set_is_ireconstructable_only() -> None:
    vm, _ = _build_vm()
    assert isinstance(vm, IReconstructable)


def test_unbound_vm_reports_no_bound_note_and_is_clean() -> None:
    vm, _ = _build_vm()
    assert vm.has_bound_note is False
    assert vm.is_dirty.value is False
    assert vm.is_valid.value is False  # empty title


def test_bind_to_creates_snapshot_and_resets_dirty() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    assert vm.has_bound_note is True
    assert vm.is_dirty.value is False
    assert vm.is_valid.value is True
    assert vm.snapshot.title == "Hello"


def test_mutating_draft_sets_is_dirty_true() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    vm.draft = _sample_note(title="Edited")
    assert vm.is_dirty.value is True
    assert vm.is_valid.value is True


def test_empty_title_is_not_valid() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note(title="   "))
    assert vm.is_valid.value is False


def test_approve_command_can_execute_requires_is_dirty_and_is_valid() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    # Clean + valid → cannot approve.
    assert vm.approve_command.can_execute() is False
    # Dirty but invalid → cannot approve.
    vm.draft = _sample_note(title="")
    assert vm.is_dirty.value is True
    assert vm.is_valid.value is False
    assert vm.approve_command.can_execute() is False
    # Dirty and valid → can approve.
    vm.draft = _sample_note(title="Updated")
    assert vm.approve_command.can_execute() is True


async def test_approve_persists_and_publishes_notification() -> None:
    vm, nh = _build_vm(with_notification_hub=True)
    assert nh is not None
    # Round-3 Important C-I2: subscribe BEFORE approve so we actually
    # observe the "Saved" notification fire (the prior version only asserted
    # the snapshot advance, leaving the notification side untested).
    from vmx.notifications import Notification

    observed: list[Notification] = []
    nh.pending.subscribe(
        on_next=lambda snap: [observed.append(n) for n in snap if n not in observed]
    )
    vm.bind_to(_sample_note())
    vm.draft = _sample_note(title="Edited title")
    await vm.approve_async()
    # Snapshot advances on success.
    assert vm.snapshot.title == "Edited title"
    assert vm.is_dirty.value is False
    # Notification posted — assert exactly one "Saved" with the new title.
    saved = [n for n in observed if "Saved" in n.message and "Edited title" in n.message]
    assert len(saved) == 1


def test_deny_restores_snapshot() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note(title="Snap"))
    vm.draft = _sample_note(title="Edited")
    assert vm.is_dirty.value is True
    vm.deny_command.execute()
    assert vm.is_dirty.value is False
    assert vm.draft.title == "Snap"


def test_add_tag_command_appends_unique_tag_and_clears_tag_draft() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    vm.tag_draft = "beta"
    assert vm.add_tag_command.can_execute() is True
    vm.add_tag_command.execute()
    assert "beta" in vm.draft.tags
    assert vm.tag_draft == ""
    # Re-adding the same tag (case-insensitive) is a no-op.
    vm.tag_draft = "BETA"
    vm.add_tag_command.execute()
    assert vm.draft.tags.count("beta") == 1


def test_remove_tag_drops_tag_case_insensitively() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    assert "alpha" in vm.draft.tags
    vm.remove_tag("ALPHA")
    assert "alpha" not in vm.draft.tags


def test_tag_draft_setter_is_no_op_on_equal_value() -> None:
    vm, _ = _build_vm()
    vm.tag_draft = "x"
    vm.tag_draft = "x"  # no second emission expected; assertion via no exception.
    assert vm.tag_draft == "x"


def test_builder_requires_name_and_repository() -> None:
    with pytest.raises(ValueError, match="name"):
        NoteFormVM.builder().build()
    with pytest.raises(ValueError, match="repository"):
        NoteFormVM.builder().name("x").build()


def test_dispose_releases_form_and_commands() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED


# ── Phase 5.b binding-gap #1: per-field scalar setters ───────────────────────


def test_title_scalar_setter_updates_draft_and_flips_dirty() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note(title="Original"))
    assert vm.title == "Original"
    vm.title = "Edited"
    assert vm.title == "Edited"
    assert vm.draft.title == "Edited"
    assert vm.is_dirty.value is True


def test_body_scalar_setter_updates_draft() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    vm.body = "new body text"
    assert vm.body == "new body text"
    assert vm.draft.body == "new body text"
    assert vm.is_dirty.value is True


def test_starred_scalar_setter_updates_draft() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    assert vm.starred is False
    vm.starred = True
    assert vm.starred is True
    assert vm.draft.starred is True
    assert vm.is_dirty.value is True


def test_scalar_setters_are_no_ops_on_equal_value() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note(title="Same"))
    vm.title = "Same"
    assert vm.is_dirty.value is False


def test_scalar_setters_are_no_ops_when_unbound() -> None:
    vm, _ = _build_vm()
    # No bound note → setters silently no-op (matches draft.setter contract).
    vm.title = "x"
    vm.body = "y"
    vm.starred = True
    assert vm.has_bound_note is False


def test_tags_accessor_proxies_to_draft() -> None:
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    assert vm.tags == ("alpha",)


def test_tags_text_derived_renders_comma_joined_string() -> None:
    """Round-3 Important C-I1: ``tags_text`` is a DerivedProperty that
    re-projects on each draft mutation, so widgets bound through
    ``bind_derived_property`` render "alpha, beta" instead of the raw
    tuple repr. Parity with the C# / TS ``tagsText`` accessor.
    """
    import dataclasses

    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    assert vm.tags_text.value == "alpha"
    vm.draft = dataclasses.replace(vm.draft, tags=("alpha", "beta"))
    assert vm.tags_text.value == "alpha, beta"


def test_bind_to_disposes_prior_hub_subscription() -> None:
    """Round-3 Important C-I3 (strengthened by Round-4 Minor-1): each
    ``bind_to`` must dispose the previous hub subscription so the prior
    closure (and its FormVM reference) does not leak across rebinds.

    Round-4 Minor-1: the earlier version of this test only asserted that
    ``second_sub is not first_sub`` — which would still pass even if
    ``bind_to`` skipped the ``.dispose()`` call (the assignment is always
    fresh). Spy on the actual disposal so removing the disposal would fail
    this test.
    """
    from unittest.mock import patch

    vm, _ = _build_vm()
    vm.bind_to(_sample_note(title="A"))
    first_sub = vm._bind_subscription  # type: ignore[attr-defined]
    assert first_sub is not None

    # Wrap the first subscription's dispose so we can observe whether the
    # second bind_to actually disposes it (rather than just orphaning it).
    disposed_calls: list[None] = []
    real_dispose = first_sub.dispose

    def _tracking_dispose() -> None:
        disposed_calls.append(None)
        real_dispose()

    with patch.object(first_sub, "dispose", side_effect=_tracking_dispose):
        vm.bind_to(_sample_note(title="B"))

    # The disposal of the prior subscription must have been observed —
    # removing the explicit `.dispose()` call in bind_to would skip this.
    assert disposed_calls, "prior _bind_subscription.dispose() must have fired"

    second_sub = vm._bind_subscription  # type: ignore[attr-defined]
    assert second_sub is not None
    assert second_sub is not first_sub  # a fresh subscription was created
    # The second subscription is still live for the active form.
    vm.title = "B-edited"
    assert vm.is_dirty.value is True


def test_unbind_clears_tag_draft_buffer() -> None:
    """R5 Minor: unbind must reset the user-typed tag input buffer.

    Today the tag draft survives across binding transitions, so after
    deleting the selected note the chip input still shows the orphan
    text. ``unbind`` resets ``tag_draft`` alongside the form / bound
    model for cross-flavor parity with C# ``TagDraft = string.Empty``
    and TS ``this.tagDraft = ""``.
    """
    vm, _ = _build_vm()
    vm.bind_to(_sample_note())
    vm.tag_draft = "secur"
    assert vm.tag_draft == "secur"

    vm.unbind()

    assert vm.tag_draft == ""
    assert vm.has_bound_note is False


def test_after_bind_to_deny_command_property_changed_fires() -> None:
    """Round-3 Important B-I2: bindings on ``deny_command`` must observe
    the rebind. ``bind_to`` re-emits ``_emit_draft_changes`` which now
    includes ``deny_command`` / ``approve_command`` PropertyChangedMessage.
    """
    from vmx import PropertyChangedMessage
    from vmx.messages.protocols import Message

    vm, _ = _build_vm()
    observed: list[str] = []

    def _capture(m: Message) -> None:
        if isinstance(m, PropertyChangedMessage) and m.sender is vm:
            observed.append(m.property_name)

    vm.hub.messages.subscribe(on_next=_capture)
    vm.bind_to(_sample_note())
    assert "deny_command" in observed
    assert "approve_command" in observed
