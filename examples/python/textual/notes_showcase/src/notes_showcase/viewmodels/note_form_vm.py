"""NoteFormVM — editor pane for the currently selected note.

VMx-API adaptation: :class:`vmx.FormVM` is a stand-alone helper rather than a
``ComponentVM`` subclass. ``NoteFormVM`` wraps a strict-mode
``FormVM[NoteModel]`` so the same approve/deny lifecycle is exposed under
``ComponentVM`` semantics. ``approve_command.can_execute`` is gated on
``is_dirty AND is_valid`` (FormVM's strict mode supplies the ``is_dirty``
half; the showcase layers the ``is_valid`` check on top).
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import cast

from vmx import (
    ComponentVM,
    DerivedProperty,
    FormVM,
    IReconstructable,
    MessageHub,
    PropertyChangedMessage,
    RelayCommand,
    RxDispatcher,
    from_sources,
)
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub, Notification, NotificationType
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.note_repository import INoteRepository

_EMPTY_NOTE = NoteModel(
    id="",
    notebook_id="",
    title="",
    tags=(),
    body="",
    starred=False,
    created_at=datetime.fromtimestamp(0),
    updated_at=datetime.fromtimestamp(0),
)


class NoteFormVM(ComponentVM, IReconstructable):
    """Editor VM bound to a single :class:`NoteModel` at a time."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        repository: INoteRepository,
        notification_hub: INotificationHub | None = None,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._repo = repository
        self._notification_hub = notification_hub
        self._form: FormVM[NoteModel] | None = None
        self._tag_draft: str = ""

        from reactivex.subject import BehaviorSubject

        self._self_subject: BehaviorSubject[NoteFormVM] = BehaviorSubject(self)
        self._is_dirty: DerivedProperty[bool] = from_sources(
            self._self_subject,
            transform=lambda nf: cast(NoteFormVM, nf)._compute_is_dirty(),
        )
        self._is_valid: DerivedProperty[bool] = from_sources(
            self._self_subject,
            transform=lambda nf: cast(NoteFormVM, nf)._compute_is_valid(),
        )

        self._approve_command = (
            RelayCommand.builder()
            .predicate(lambda: self.is_dirty.value and self.is_valid.value)
            .task(self._approve_fire_and_forget)
            .build()
        )
        self._add_tag_command = (
            RelayCommand.builder()
            .predicate(lambda: self.has_bound_note and bool(self._tag_draft.strip()))
            .task(self._add_tag)
            .build()
        )
        self._remove_tag_command_of_t: RelayCommand = (
            # Simple non-parameterised: caller passes tag via remove_tag() method.
            RelayCommand.builder().task(lambda: None).build()
        )

    # ── Convenience hub accessor ───────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    # ── Bound state ────────────────────────────────────────────────────────
    @property
    def has_bound_note(self) -> bool:
        return self._form is not None

    @property
    def draft(self) -> NoteModel:
        return self._form.model if self._form is not None else _EMPTY_NOTE

    @draft.setter
    def draft(self, value: NoteModel) -> None:
        if self._form is None:
            return
        self._form.set_model(value)
        self._emit_draft_changes()

    # Phase 5.b binding gap #1: NoteModel is an immutable record, so widgets
    # cannot two-way bind to ``draft.title`` (the chain is read-only). Expose
    # per-field scalar setters on the form itself so the Textual ``Input`` /
    # ``TextArea`` / ``Checkbox`` widgets can ``bind_property_two_way`` to
    # ``title`` / ``body`` / ``starred`` and edits actually round-trip back
    # into the form.
    @property
    def title(self) -> str:
        return self.draft.title

    @title.setter
    def title(self, value: str) -> None:
        if self._form is None or self.draft.title == value:
            return
        self.draft = dataclasses.replace(self.draft, title=value)

    @property
    def body(self) -> str:
        return self.draft.body

    @body.setter
    def body(self, value: str) -> None:
        if self._form is None or self.draft.body == value:
            return
        self.draft = dataclasses.replace(self.draft, body=value)

    @property
    def starred(self) -> bool:
        return self.draft.starred

    @starred.setter
    def starred(self, value: bool) -> None:
        if self._form is None or self.draft.starred == value:
            return
        self.draft = dataclasses.replace(self.draft, starred=value)

    @property
    def tags(self) -> tuple[str, ...]:
        return self.draft.tags

    @property
    def snapshot(self) -> NoteModel:
        return self._form.snapshot if self._form is not None else _EMPTY_NOTE

    # ── Derived properties ─────────────────────────────────────────────────
    @property
    def is_dirty(self) -> DerivedProperty[bool]:
        return self._is_dirty

    @property
    def is_valid(self) -> DerivedProperty[bool]:
        return self._is_valid

    def _compute_is_dirty(self) -> bool:
        return self._form.is_dirty if self._form is not None else False

    def _compute_is_valid(self) -> bool:
        return bool(self.draft.title.strip())

    # ── Tag draft + commands ───────────────────────────────────────────────
    @property
    def tag_draft(self) -> str:
        return self._tag_draft

    @tag_draft.setter
    def tag_draft(self, value: str) -> None:
        if self._tag_draft == value:
            return
        self._tag_draft = value
        self._hub.send(PropertyChangedMessage.create(self, self._name, "tag_draft"))
        self._raise_property_changed("tag_draft")

    @property
    def approve_command(self) -> RelayCommand:
        return self._approve_command

    @property
    def deny_command(self) -> RelayCommand:
        if self._form is None:
            # Return a permanent no-op command so views can bind unconditionally.
            return self._remove_tag_command_of_t
        return self._form.deny_command

    @property
    def add_tag_command(self) -> RelayCommand:
        return self._add_tag_command

    def remove_tag(self, tag: str) -> None:
        """Imperative tag removal (caller provides the tag)."""
        if not self.has_bound_note or not tag:
            return
        current = self.draft
        new_tags = tuple(t for t in current.tags if t.lower() != tag.lower())
        self.draft = self._replace_tags(current, new_tags)

    def _add_tag(self) -> None:
        if self._form is None:
            return
        tag = self._tag_draft.strip()
        if not tag:
            return
        current = self.draft
        if any(t.lower() == tag.lower() for t in current.tags):
            return
        self.draft = self._replace_tags(current, (*current.tags, tag))
        self.tag_draft = ""

    @staticmethod
    def _replace_tags(model: NoteModel, tags: tuple[str, ...]) -> NoteModel:
        return NoteModel(
            id=model.id,
            notebook_id=model.notebook_id,
            title=model.title,
            tags=tags,
            body=model.body,
            starred=model.starred,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    # ── Bind / approve ─────────────────────────────────────────────────────
    def bind_to(self, note: NoteModel) -> None:
        """Replace the inner :class:`FormVM` with one bound to *note*."""
        if self._form is not None:
            self._form.dispose()
        form = FormVM(
            initial=note,
            persister=self._persist,
            hub=self._hub,
            strict=True,
        )
        form.on_approved.subscribe(on_next=lambda _: self._emit_draft_changes())
        self._form = form
        # FormVM.deny_command reverts the inner model but does not know about
        # our derived properties — listen for FormRevertedMessage on the hub
        # and re-emit our own draft changes so `is_dirty` / `is_valid` refresh.
        from vmx.messages.form_reverted import FormRevertedMessage

        def _on_msg(m: Message) -> None:
            if isinstance(m, FormRevertedMessage) and m.sender is form:
                self._emit_draft_changes()

        self._hub.messages.subscribe(on_next=_on_msg)
        self._emit_draft_changes()

    async def approve_async(self) -> None:
        """Awaitable approve cycle: persist + publish "Saved" notification."""
        if self._form is None:
            return
        await self._form.approve_async()
        self._emit_draft_changes()
        if self._notification_hub is not None:
            self._notification_hub.post(
                Notification(
                    NotificationType.NOTIFICATION,
                    f'Saved "{self._form.snapshot.title}"',
                )
            )

    async def _persist(self, note: NoteModel) -> None:
        await self._repo.save_note(note)

    def _approve_fire_and_forget(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.approve_async())
            task.add_done_callback(lambda t: t.exception())
        except RuntimeError:
            asyncio.run(self.approve_async())

    def _emit_draft_changes(self) -> None:
        self._self_subject.on_next(self)
        # Includes the per-field scalars (title/body/starred/tags) so widgets
        # two-way bound via the adapter receive PropertyChangedMessage and
        # re-read. See Phase 5.b binding gap #1.
        for prop in (
            "draft",
            "snapshot",
            "is_dirty",
            "is_valid",
            "title",
            "body",
            "starred",
            "tags",
        ):
            self._hub.send(PropertyChangedMessage.create(self, self._name, prop))
            self._raise_property_changed(prop)

    # ── Lifecycle override ─────────────────────────────────────────────────
    def _on_dispose(self) -> None:
        if self._form is not None:
            self._form.dispose()
        self._approve_command.dispose()
        self._add_tag_command.dispose()
        self._remove_tag_command_of_t.dispose()
        self._is_dirty.dispose()
        self._is_valid.dispose()
        self._self_subject.on_completed()
        self._self_subject.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> NoteFormVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase NoteFormVMBuilder.
        return NoteFormVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class NoteFormVMBuilder:
    """Immutable fluent builder for :class:`NoteFormVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _repo: INoteRepository | None = None
    _notification_hub: INotificationHub | None = None

    def name(self, value: str) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(self, hub: MessageHub[Message], dispatcher: Dispatcher) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def repository(self, repo: INoteRepository) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _repo=repo)

    def notification_hub(self, nh: INotificationHub) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _notification_hub=nh)

    def build(self) -> NoteFormVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._repo is None:
            raise ValueError("repository is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = self._dispatcher if self._dispatcher is not None else RxDispatcher.immediate()
        return NoteFormVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            repository=self._repo,
            notification_hub=self._notification_hub,
        )
