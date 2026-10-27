"""A small notebook built from VMx primitives.

- Each note is a ``ComponentVMOf[NoteModel]`` leaf.
- The notebook is a ``CompositeVM`` that owns the notes and tracks ``current``.
- ``save_current`` is a ``RelayCommand`` that writes the current note to a
  store. A store error propagates to the caller of ``execute()``.

Replace ``InMemoryNoteStore`` with your own persistence adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vmx import (
    ComponentVMOf,
    ComponentVMOfBuilder,
    CompositeVM,
    CompositeVMBuilder,
    Dispatcher,
    Message,
    MessageHub,
    RelayCommand,
    RxDispatcher,
)


@dataclass(frozen=True)
class NoteModel:
    id: str
    title: str
    body: str


NoteVM = ComponentVMOf[NoteModel]


def build_note(model: NoteModel, hub: MessageHub[Message], dispatcher: Dispatcher) -> NoteVM:
    """Build one note leaf. The annotation binds the builder's model type."""
    builder: ComponentVMOfBuilder[NoteModel] = ComponentVMOf.builder()
    return (
        builder.name(f"note-{model.id}")
        .model(model)
        .modeled_hinter(lambda m: m.title)
        .services(hub, dispatcher)
        .build()
    )


class NoteConflictError(Exception):
    """The store rejects a save when another note already uses the title."""

    def __init__(self, title: str) -> None:
        super().__init__(f'another note already uses the title "{title}"')
        self.title = title


class InMemoryNoteStore:
    def __init__(self) -> None:
        self._notes: dict[str, NoteModel] = {}

    def save(self, note: NoteModel) -> None:
        for other in self._notes.values():
            if other.id != note.id and other.title == note.title:
                raise NoteConflictError(note.title)
        self._notes[note.id] = note

    def get(self, note_id: str) -> NoteModel | None:
        return self._notes.get(note_id)

    def __len__(self) -> int:
        return len(self._notes)


class NotebookApp:
    def __init__(self, store: InMemoryNoteStore, seed: Sequence[NoteModel]) -> None:
        self.hub: MessageHub[Message] = MessageHub()
        # `immediate()` runs foreground and background work synchronously. A UI
        # host passes its own scheduler pair to `RxDispatcher(...)` instead.
        dispatcher = RxDispatcher.immediate()
        notes = [build_note(model, self.hub, dispatcher) for model in seed]
        builder: CompositeVMBuilder[NoteVM] = CompositeVM.builder()
        self.notebook: CompositeVM[NoteVM] = (
            builder.name("notebook")
            .services(self.hub, dispatcher)
            .children(lambda: notes)
            .build()
        )
        self._store = store
        # Re-evaluate `can_execute` whenever any message arrives on this hub.
        self.save_current = (
            RelayCommand.builder()
            .predicate(self._can_save)
            .task(self._save)
            .triggers(self.hub.messages)
            .build()
        )
        self._disposed = False

    def _can_save(self) -> bool:
        current = self.notebook.current
        return (
            self.notebook.is_constructed
            and current is not None
            and current.model.title.strip() != ""
        )

    def _save(self) -> None:
        current = self.notebook.current
        if current is not None:
            self._store.save(current.model)

    def start(self) -> None:
        """Construct the notebook (and its notes) and select the first note."""
        self.notebook.construct()
        self.notebook.current = next(iter(self.notebook), None)

    def rename_current(self, title: str) -> None:
        """Replace the current note's title. Models are immutable records."""
        current = self.notebook.current
        if current is None:
            raise RuntimeError("no note is selected")
        current.model = replace(current.model, title=title)

    def select(self, note_id: str) -> None:
        for note in self.notebook:
            if note.model.id == note_id:
                self.notebook.current = note
                return
        raise KeyError(f"unknown note {note_id}")

    def dispose(self) -> None:
        """Dispose the command first, then the VMs, then the hub."""
        if self._disposed:
            return
        self._disposed = True
        self.save_current.dispose()
        self.notebook.dispose()
        self.hub.dispose()
