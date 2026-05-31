"""StatusBarVM — read-only VM driving the three status-bar slots.

Each slot (``note_count_text``, ``starred_text``, ``editing_text``) is a
:class:`vmx.DerivedProperty` whose source is a :class:`reactivex.BehaviorSubject`
that re-emits the watched VM whenever a relevant ``PropertyChangedMessage``
appears on its hub. Equality-guard inside :class:`DerivedProperty` means
``value_changed`` only fires when the rendered string actually differs.
"""

from __future__ import annotations

import dataclasses
from typing import cast

from reactivex.abc import DisposableBase
from reactivex.subject import BehaviorSubject

from vmx import (
    ComponentVM,
    DerivedProperty,
    MessageHub,
    PropertyChangedMessage,
    RxDispatcher,
    from_sources,
)
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher

from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM


class StatusBarVM(ComponentVM):
    """Three-slot status bar fed by three source VMs."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        notes_view: NotesViewVM,
        notebooks: NotebooksRootVM,
        note_form: NoteFormVM,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._notes_view = notes_view
        self._notebooks = notebooks
        self._note_form = note_form

        self._notes_view_subject: BehaviorSubject[NotesViewVM] = BehaviorSubject(
            notes_view
        )
        self._notebooks_subject: BehaviorSubject[NotebooksRootVM] = BehaviorSubject(
            notebooks
        )
        self._note_form_subject: BehaviorSubject[NoteFormVM] = BehaviorSubject(
            note_form
        )

        def _resub(subject: BehaviorSubject[object], target: object) -> DisposableBase:
            def _on_msg(m: Message) -> None:
                if isinstance(m, PropertyChangedMessage) and m.sender is target:
                    subject.on_next(target)

            return notes_view.hub.messages.subscribe(on_next=_on_msg)

        self._subs: list[DisposableBase] = [
            _resub(
                cast("BehaviorSubject[object]", self._notes_view_subject), notes_view
            ),
            _resub(cast("BehaviorSubject[object]", self._notebooks_subject), notebooks),
            _resub(cast("BehaviorSubject[object]", self._note_form_subject), note_form),
        ]

        self._note_count_text: DerivedProperty[str] = from_sources(
            self._notes_view_subject,
            transform=lambda nv: _render_note_count(cast(NotesViewVM, nv)),
        )
        self._starred_text: DerivedProperty[str] = from_sources(
            self._notes_view_subject,
            transform=lambda nv: _render_starred(cast(NotesViewVM, nv)),
        )
        self._editing_text: DerivedProperty[str] = from_sources(
            self._note_form_subject,
            transform=lambda nf: _render_editing(cast(NoteFormVM, nf)),
        )

    # ── Public surface ─────────────────────────────────────────────────────
    @property
    def hub(self) -> MessageHub[Message]:
        return self._hub

    @property
    def note_count_text(self) -> DerivedProperty[str]:
        return self._note_count_text

    @property
    def starred_text(self) -> DerivedProperty[str]:
        return self._starred_text

    @property
    def editing_text(self) -> DerivedProperty[str]:
        return self._editing_text

    # ── Lifecycle override ─────────────────────────────────────────────────
    def _on_dispose(self) -> None:
        for sub in self._subs:
            sub.dispose()
        self._note_count_text.dispose()
        self._starred_text.dispose()
        self._editing_text.dispose()
        self._notes_view_subject.on_completed()
        self._notes_view_subject.dispose()
        self._notebooks_subject.on_completed()
        self._notebooks_subject.dispose()
        self._note_form_subject.on_completed()
        self._note_form_subject.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> StatusBarVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase StatusBarVMBuilder.
        return StatusBarVMBuilder()


def _render_note_count(nv: NotesViewVM) -> str:
    count = len(nv.filtered_items)
    return f"{count} note{'' if count == 1 else 's'}"


def _render_starred(nv: NotesViewVM) -> str:
    k = sum(1 for n in nv.filtered_items if n.model.starred)
    return f"{k} starred"


def _render_editing(nf: NoteFormVM) -> str:
    if not nf.has_bound_note:
        return "No selection"
    dirty_marker = " *" if nf.is_dirty.value else ""
    return f"Editing: {nf.draft.title}{dirty_marker}"


@dataclasses.dataclass(frozen=True, slots=True)
class StatusBarVMBuilder:
    """Immutable fluent builder for :class:`StatusBarVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHub[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _notes_view: NotesViewVM | None = None
    _notebooks: NotebooksRootVM | None = None
    _note_form: NoteFormVM | None = None

    def name(self, value: str) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHub[Message], dispatcher: Dispatcher
    ) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def notes_view(self, value: NotesViewVM) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _notes_view=value)

    def notebooks(self, value: NotebooksRootVM) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _notebooks=value)

    def note_form(self, value: NoteFormVM) -> StatusBarVMBuilder:
        return dataclasses.replace(self, _note_form=value)

    def build(self) -> StatusBarVM:
        if self._name is None:
            raise ValueError("name is required")
        if self._notes_view is None:
            raise ValueError("notes_view is required")
        if self._notebooks is None:
            raise ValueError("notebooks is required")
        if self._note_form is None:
            raise ValueError("note_form is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
        return StatusBarVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            notes_view=self._notes_view,
            notebooks=self._notebooks,
            note_form=self._note_form,
        )
