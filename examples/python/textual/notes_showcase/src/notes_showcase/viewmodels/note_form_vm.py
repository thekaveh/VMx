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

from reactivex import Observable
from reactivex.abc import DisposableBase

from vmx import (
    ComponentVM,
    DerivedProperty,
    DiscriminatorVM,
    FormVM,
    IReconstructable,
    MessageHub,
    MessageHubProto,
    PropertyChangedMessage,
    RelayCommand,
    RelayCommandOf,
    RxDispatcher,
    SearchableState,
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
_TITLE_REQUIRED = "Title is required."


class NoteFormVM(ComponentVM, IReconstructable):
    """Editor VM bound to a single :class:`NoteModel` at a time."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        repository: INoteRepository,
        notification_hub: INotificationHub | None = None,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._repo = repository
        self._notification_hub = notification_hub
        self._form: FormVM[NoteModel] | None = None
        self._tag_draft: str = ""
        self._editor_mode: DiscriminatorVM[str] = DiscriminatorVM("edit")
        self._tag_catalog: tuple[str, ...] = ()
        self._tag_suggestions: tuple[str, ...] = ()
        # Round-3 Important C-I3: track the hub subscription created by
        # ``bind_to`` so we can dispose the previous one before re-subscribing
        # (previously the prior closure leaked on every rebind).
        self._bind_subscription: DisposableBase | None = None

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
        # Round-3 Important C-I1: render the tag tuple as a flat, comma-joined
        # string for the Textual chip strip. Binding ``Static.renderable``
        # directly to ``tags`` (a ``tuple[str, ...]``) emits Python repr
        # ("('alpha',)") instead of "alpha". The DerivedProperty re-projects
        # whenever ``_self_subject`` re-emits (i.e. on every draft mutation).
        # Mirrors the C# NoteFormVM.TagsText (Phase 5.a) and TS NoteFormVM
        # tagsText (Phase 5.c) accessors.
        self._tags_text: DerivedProperty[str] = from_sources(
            self._self_subject,
            transform=lambda nf: ", ".join(cast(NoteFormVM, nf).tags),
        )
        self._tag_search: SearchableState[str] = SearchableState(
            items=lambda: self._tag_catalog,
            predicate=lambda tag, term: self._tag_matches(tag, term),
            debounce_seconds=0,
            scheduler=dispatcher.foreground,
        )
        self._tag_search_subscription = self._tag_search.filtered.subscribe(
            on_next=self._set_tag_suggestions
        )

        # Triggered by the self-subject so bound Buttons' disabled state
        # tracks every draft/bind change — without a trigger,
        # can_execute_changed never fired and the Save button stayed
        # permanently disabled in the UI (real-wiring audit, pass 5).
        self._approve_command = (
            RelayCommand.builder()
            .predicate(lambda: self.is_dirty.value and self.is_valid.value)
            .task(self._approve_fire_and_forget)
            .triggers(self._self_subject)
            .build()
        )
        self._add_tag_command = (
            RelayCommand.builder()
            .predicate(lambda: self.has_bound_note and bool(self._tag_draft.strip()))
            .task(self._add_tag)
            .triggers(self._self_subject)
            .build()
        )
        # Parameterised remove-tag command — parity with C# RemoveTagCommand
        # (RelayCommand<string?>) and TS removeTagCommand (RelayCommandOf<string>).
        # Spec §6.2 requires NoteFormVM to expose this as a public VM member.
        self._remove_tag_command: RelayCommandOf[str] = (
            RelayCommandOf[str]
            .builder()
            .predicate(lambda tag: self.has_bound_note and bool(tag))
            .task(self._remove_tag)
            .build()
        )
        # Stable deny delegate: Textual's bind_command captures the command
        # object once at mount, so returning a per-form (or no-op fallback)
        # command from ``deny_command`` left the Revert button permanently
        # wired to whatever was bound at mount time (real-wiring audit,
        # pass 5). C#/TS re-resolve their bindings on every change
        # notification, so their no-op-fallback pattern is safe there; here
        # the property must hand out one object for the VM's lifetime.
        self._deny_command: RelayCommand = (
            RelayCommand.builder().task(self._deny_current).build()
        )
        self._show_edit_mode_command = (
            RelayCommand.builder()
            .predicate(lambda: not self.is_edit_mode)
            .task(lambda: self._editor_mode.set_active_key("edit"))
            .triggers(self._self_subject)
            .build()
        )
        self._show_preview_mode_command = (
            RelayCommand.builder()
            .predicate(lambda: not self.is_preview_mode)
            .task(lambda: self._editor_mode.set_active_key("preview"))
            .triggers(self._self_subject)
            .build()
        )
        self._editor_mode_subscription = self._editor_mode.active_changed.subscribe(
            on_next=lambda _mode: self._emit_editor_mode_changes()
        )
        # Emits the persisted NoteModel after each successful save; the
        # workspace uses it to refresh the note-list row labels.
        from reactivex.subject import Subject as _Subject

        self._on_saved: _Subject[NoteModel] = _Subject()

    # ── Convenience hub accessor ───────────────────────────────────────────
    @property
    def hub(self) -> MessageHubProto[Message]:
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

    @property
    def tags_text(self) -> DerivedProperty[str]:
        """Comma-joined tag list — bind ``Static.renderable`` to this so the
        Textual chip strip renders "alpha, beta" instead of the raw tuple
        repr. Mirrors the C# / TS ``tagsText`` accessor.
        """
        return self._tags_text

    def _compute_is_dirty(self) -> bool:
        return self._form.is_dirty if self._form is not None else False

    def _compute_is_valid(self) -> bool:
        return self._form.is_valid if self._form is not None else False

    @property
    def title_error(self) -> str | None:
        return self._form.field_error("title") if self._form is not None else None

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
        self._tag_search.search_term = value
        self._tag_search.search()
        # Nudge command predicates (add-tag gates on a non-empty draft).
        self._self_subject.on_next(self)

    @property
    def approve_command(self) -> RelayCommand:
        return self._approve_command

    @property
    def deny_command(self) -> RelayCommand:
        """Stable command that reverts the currently-bound form (no-op when
        unbound) — one object for the VM's lifetime so a bind-once view stays
        wired across form rebinds."""
        return self._deny_command

    @property
    def on_saved(self) -> Observable[NoteModel]:
        """Emits the persisted :class:`NoteModel` after each successful save."""
        return self._on_saved

    @property
    def add_tag_command(self) -> RelayCommand:
        return self._add_tag_command

    @property
    def remove_tag_command(self) -> RelayCommandOf[str]:
        """Parameterised remove-tag command — invoke with the tag string to
        drop. Parity with C# ``RemoveTagCommand`` and TS ``removeTagCommand``.
        """
        return self._remove_tag_command

    @property
    def tag_suggestions(self) -> tuple[str, ...]:
        return self._tag_suggestions

    @property
    def tag_suggestions_text(self) -> str:
        return ", ".join(self._tag_suggestions)

    @property
    def editor_mode(self) -> str:
        return self._editor_mode.active_key

    @property
    def is_preview_mode(self) -> bool:
        return self._editor_mode.is_active("preview")

    @property
    def is_edit_mode(self) -> bool:
        return self._editor_mode.is_active("edit")

    @property
    def show_edit_mode_command(self) -> RelayCommand:
        return self._show_edit_mode_command

    @property
    def show_preview_mode_command(self) -> RelayCommand:
        return self._show_preview_mode_command

    def remove_tag(self, tag: str) -> None:
        """Imperative tag removal (caller provides the tag).

        Equivalent to ``remove_tag_command.execute(tag)``; kept as a thin
        Python-side helper for tests and ad-hoc callers.
        """
        self._remove_tag(tag)

    def _remove_tag(self, tag: str | None) -> None:
        if not self.has_bound_note or not tag:
            return
        current = self.draft
        new_tags = tuple(t for t in current.tags if t.lower() != tag.lower())
        if new_tags == current.tags:
            return
        self.draft = self._replace_tags(current, new_tags)
        self._tag_search.search()

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
        self._tag_search.search()

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
        # Round-3 Important C-I3: dispose any prior hub subscription before
        # re-subscribing below so the closure for the old form doesn't leak
        # (each bind_to used to leave the previous one alive forever).
        if self._bind_subscription is not None:
            self._bind_subscription.dispose()
            self._bind_subscription = None
        form = FormVM(
            initial=note,
            persister=self._persist,
            hub=self._hub,
            strict=True,
            validators={
                "title": lambda m: _TITLE_REQUIRED if not m.title.strip() else None
            },
        )
        form.on_approved.subscribe(on_next=self._handle_approved)
        self._form = form
        # FormVM.deny_command reverts the inner model but does not know about
        # our derived properties — listen for FormRevertedMessage on the hub
        # and re-emit our own draft changes so `is_dirty` / `is_valid` refresh.
        from vmx.messages.form_reverted import FormRevertedMessage

        def _on_msg(m: Message) -> None:
            if isinstance(m, FormRevertedMessage) and m.sender is form:
                self._emit_draft_changes()

        self._bind_subscription = self._hub.messages.subscribe(on_next=_on_msg)
        self._emit_draft_changes()

    def unbind(self) -> None:
        """Clear the form back to its initial empty state.

        Round-4 Important-1: called by :class:`WorkspaceVM` when
        ``notes_view.current`` transitions to ``None`` (e.g. the selected
        note is deleted in :meth:`NotesViewVM._delete_note_async`) so the
        right-pane editor does not display ghost data from the just-removed
        note. Mirrors C# ``NoteFormVM.Unbind`` and TS ``NoteFormVM.unbind``.

        Round-5 Minor: also reset ``tag_draft``. The user-typed tag input
        buffer is part of the editor state, so a binding transition must
        clear it too — otherwise the chip input still shows the orphan
        text after the note disappears. Cross-flavor parity with C#
        ``TagDraft = string.Empty`` and TS ``this.tagDraft = ""``.
        """
        had_tag_draft = self._tag_draft != ""
        if self._form is None and self._bind_subscription is None and not had_tag_draft:
            return
        if self._form is not None:
            self._form.dispose()
            self._form = None
        if self._bind_subscription is not None:
            self._bind_subscription.dispose()
            self._bind_subscription = None
        if had_tag_draft:
            self._tag_draft = ""
            self._hub.send(PropertyChangedMessage.create(self, self._name, "tag_draft"))
            self._raise_property_changed("tag_draft")
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
                    f"Saved “{self._form.snapshot.title}”",
                )
            )
        await self.refresh_tag_suggestions_async()

    def _handle_approved(self, model: NoteModel) -> None:
        self._emit_draft_changes()
        self._on_saved.on_next(model)

    def _deny_current(self) -> None:
        form = self._form
        if form is not None:
            form.deny_command.execute()

    async def _persist(self, note: NoteModel) -> None:
        await self._repo.save_note(note)

    async def refresh_tag_suggestions_async(self) -> None:
        try:
            _notebooks, notes = await self._repo.load_all()
            seen: dict[str, str] = {}
            for note in notes:
                for raw in note.tags:
                    tag = raw.strip()
                    if tag:
                        seen.setdefault(tag.lower(), tag)
            self._tag_catalog = tuple(sorted(seen.values(), key=str.lower))
        except Exception:
            self._tag_catalog = ()
        self._tag_search.search()

    def _approve_fire_and_forget(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.approve_async())
            task.add_done_callback(lambda t: t.exception())
        except RuntimeError:
            asyncio.run(self.approve_async())

    def _tag_matches(self, tag: str, term: str) -> bool:
        normalized = term.strip().lower()
        if not normalized:
            return False
        if normalized not in tag.lower():
            return False
        return all(existing.lower() != tag.lower() for existing in self.draft.tags)

    def _set_tag_suggestions(self, suggestions: list[str]) -> None:
        self._tag_suggestions = tuple(suggestions)
        self._emit_tag_suggestion_changes()

    def _emit_draft_changes(self) -> None:
        self._self_subject.on_next(self)
        # Includes the per-field scalars (title/body/starred/tags) so widgets
        # two-way bound via the adapter receive PropertyChangedMessage and
        # re-read. See Phase 5.b binding gap #1.
        # Round-3 Important B-I2 parity: also fire for ``approve_command`` /
        # ``deny_command``. Both are stable objects now, but consumers that
        # re-resolve on change notifications (C#/TS-style bindings) still
        # expect the signal on rebinds.
        for prop in (
            "draft",
            "snapshot",
            "is_dirty",
            "is_valid",
            "title_error",
            "title",
            "body",
            "starred",
            "tags",
            "tag_suggestions",
            "tag_suggestions_text",
            "approve_command",
            "deny_command",
        ):
            self._hub.send(PropertyChangedMessage.create(self, self._name, prop))
            self._raise_property_changed(prop)

    def _emit_editor_mode_changes(self) -> None:
        for prop in (
            "editor_mode",
            "is_preview_mode",
            "is_edit_mode",
            "show_edit_mode_command",
            "show_preview_mode_command",
        ):
            self._hub.send(PropertyChangedMessage.create(self, self._name, prop))
            self._raise_property_changed(prop)
        self._self_subject.on_next(self)

    def _emit_tag_suggestion_changes(self) -> None:
        for prop in ("tag_suggestions", "tag_suggestions_text"):
            self._hub.send(PropertyChangedMessage.create(self, self._name, prop))
            self._raise_property_changed(prop)

    # ── Lifecycle override ─────────────────────────────────────────────────
    def _on_dispose(self) -> None:
        if self._form is not None:
            self._form.dispose()
        self._approve_command.dispose()
        self._add_tag_command.dispose()
        self._remove_tag_command.dispose()
        self._deny_command.dispose()
        self._show_edit_mode_command.dispose()
        self._show_preview_mode_command.dispose()
        self._editor_mode_subscription.dispose()
        self._editor_mode.dispose()
        self._tag_search_subscription.dispose()
        self._tag_search.dispose()
        self._on_saved.on_completed()
        self._on_saved.dispose()
        self._is_dirty.dispose()
        self._is_valid.dispose()
        self._tags_text.dispose()
        if self._bind_subscription is not None:
            self._bind_subscription.dispose()
            self._bind_subscription = None
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
    _hub: MessageHubProto[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _repo: INoteRepository | None = None
    _notification_hub: INotificationHub | None = None

    def name(self, value: str) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NoteFormVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHubProto[Message], dispatcher: Dispatcher
    ) -> NoteFormVMBuilder:
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
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return NoteFormVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            repository=self._repo,
            notification_hub=self._notification_hub,
        )
