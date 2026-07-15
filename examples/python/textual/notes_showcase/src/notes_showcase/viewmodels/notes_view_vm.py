"""NotesViewVM — paged, searchable, filterable list of notes.

VMx-API adaptation: the spec calls for ``PagedComposition[NoteVM]`` as a base
class, but :class:`vmx.PagedComposition` is a read-only decorator, not a
subclass-able VM. Composition instead:

* inner storage: :class:`vmx.ObservableList` ``[NoteVM]``
  (mutable, hub-observable),
* filtered view: an :class:`~vmx.ObservableList` mirror recomputed on every
  collection / filter / search change,
* paged view: :class:`vmx.PagedComposition` over the filtered list,
* search: :class:`vmx.SearchableState` (debounced 150 ms).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import cast

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ImmediateScheduler

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.viewmodels.dialog_service import IDialogService
from notes_showcase.viewmodels.note_vm import NoteVM
from vmx import (
    ComponentVM,
    ConstructionStatus,
    DerivedProperty,
    Filterable,
    IReconstructable,
    ISearchable,
    MessageHub,
    MessageHubProto,
    ObservableList,
    Pageable,
    PagedComposition,
    RelayCommand,
    RxDispatcher,
    SearchableState,
    from_sources,
)
from vmx.messages.protocols import Message
from vmx.notifications import INotificationHub
from vmx.services.dispatcher import Dispatcher

_DEFAULT_PAGE_SIZE = 5
_DEFAULT_SEARCH_DEBOUNCE_S = 0.150


class NotesViewVM(
    ComponentVM,
    Pageable,
    ISearchable,
    IReconstructable,
):
    """Centre-pane VM for browsing/searching notes within a notebook."""

    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        repository: INoteRepository,
        page_size: int = _DEFAULT_PAGE_SIZE,
        search_debounce_seconds: float = _DEFAULT_SEARCH_DEBOUNCE_S,
        search_scheduler: SchedulerBase | None = None,
        dialog_service: IDialogService | None = None,
        notification_hub: INotificationHub | None = None,
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._repo = repository
        self._dialog_service = dialog_service
        self._notification_hub = notification_hub
        self._search_scheduler = search_scheduler or ImmediateScheduler()

        self._inner: ObservableList[NoteVM] = ObservableList()
        self._filtered: list[NoteVM] = []
        self._paged: PagedComposition[NoteVM] = PagedComposition(
            source=lambda: self._filtered,
            page_size=page_size,
        )
        # Re-broadcast paged property changes through our own hub.
        self._paged.on_property_changed.subscribe(on_next=self._on_paged_changed)

        self._show_starred_only: bool = False
        self._filter: Callable[[NoteVM], bool] | None = None
        self._current: NoteVM | None = None
        self._bound_notebook_id: str | None = None
        # Edge-case backfill (rapid-selection concurrency): bind_to_async
        # increments this token before awaiting; on resume a stale token is
        # discarded so the most-recent select wins. Parity with TS
        # NotesViewVM #activeBindingToken.
        self._active_binding_token: int = 0
        # Edge-case backfill (readonly notebook gating): mirrors the readonly
        # flag of the currently-bound notebook. Set by the WorkspaceVM when
        # the user changes notebook selection; consulted by
        # CapabilityActionsVM.add_note_command.can_execute.
        self._current_notebook_is_readonly: bool = False

        # Derived properties (replayed via a self-subject so derived recomputes
        # are triggered explicitly by `_recompute_filtered` even when no source
        # identity changed). Must be initialised BEFORE SearchableState below,
        # which fires `_recompute_filtered` synchronously during subscribe.
        from reactivex.subject import BehaviorSubject

        self._self_subject: BehaviorSubject[NotesViewVM] = BehaviorSubject(self)
        self._is_empty: DerivedProperty[bool] = from_sources(
            self._self_subject,
            transform=lambda nv: len(cast(NotesViewVM, nv)._filtered) == 0,
        )
        self._page_label: DerivedProperty[str] = from_sources(
            self._self_subject,
            transform=lambda nv: cast(NotesViewVM, nv)._build_page_label(),
        )

        self._search: SearchableState[NoteVM] = SearchableState(
            items=lambda: list(self._inner),
            predicate=lambda _item, _term: True,
            debounce_seconds=search_debounce_seconds,
            scheduler=self._search_scheduler,
        )
        # Re-run our combined filter on every debounced term update.
        self._search.filtered.subscribe(on_next=lambda _: self._recompute_filtered())

        # Paging commands (wrap PagedComposition's methods for view binding).
        self._move_to_first_page_command = (
            RelayCommand.builder()
            .predicate(lambda: self.current_page_index > 0)
            .task(self.move_to_first_page)
            .triggers(self._self_subject)
            .build()
        )
        self._move_to_previous_page_command = (
            RelayCommand.builder()
            .predicate(lambda: self.current_page_index > 0)
            .task(self.move_to_previous_page)
            .triggers(self._self_subject)
            .build()
        )
        self._move_to_next_page_command = (
            RelayCommand.builder()
            .predicate(lambda: self.current_page_index < self.page_count - 1)
            .task(self.move_to_next_page)
            .triggers(self._self_subject)
            .build()
        )
        self._move_to_last_page_command = (
            RelayCommand.builder()
            .predicate(lambda: self.current_page_index < self.page_count - 1)
            .task(self.move_to_last_page)
            .triggers(self._self_subject)
            .build()
        )

    # ── Convenience hub accessor ───────────────────────────────────────────
    @property
    def hub(self) -> MessageHubProto[Message]:
        return self._hub

    @property
    def inner(self) -> ObservableList[NoteVM]:
        return self._inner

    @property
    def filtered_items(self) -> list[NoteVM]:
        return list(self._filtered)

    @property
    def visible_items(self) -> list[NoteVM]:
        return list(self._paged.items)

    @property
    def bound_notebook_id(self) -> str | None:
        return self._bound_notebook_id

    @property
    def current_notebook_is_readonly(self) -> bool:
        """Readonly flag of the currently-bound notebook.

        Set by the host (e.g. :class:`WorkspaceVM`) on notebook selection.
        :class:`CapabilityActionsVM.add_note_command` consults this so the
        bar disables *Add Note* for readonly notebooks.
        """
        return self._current_notebook_is_readonly

    @current_notebook_is_readonly.setter
    def current_notebook_is_readonly(self, value: bool) -> None:
        if self._current_notebook_is_readonly == value:
            return
        self._current_notebook_is_readonly = value
        self._notify_property_changed("current_notebook_is_readonly")

    @property
    def dialog_service(self) -> IDialogService | None:
        """Dialog service used for delete confirmation (late-bindable)."""
        return self._dialog_service

    @dialog_service.setter
    def dialog_service(self, value: IDialogService | None) -> None:
        self._dialog_service = value

    @property
    def is_empty(self) -> DerivedProperty[bool]:
        return self._is_empty

    @property
    def page_label(self) -> DerivedProperty[str]:
        return self._page_label

    @property
    def current(self) -> NoteVM | None:
        return self._current

    @current.setter
    def current(self, value: NoteVM | None) -> None:
        if self._current is value:
            return
        self._current = value
        self._notify_property_changed("current")

    # ── ISearchable ────────────────────────────────────────────────────────
    @property
    def search_term(self) -> str:
        return self._search.search_term

    @search_term.setter
    def search_term(self, value: str) -> None:
        self._search.search_term = value

    def can_search(self) -> bool:
        return self._search.can_search()

    def search(self) -> None:
        self._search.search()

    # ── IFilterable[NoteVM] (registered below to avoid Generic MRO conflict) ──
    @property
    def filter(self) -> Callable[[NoteVM], bool] | None:
        return self._filter

    @filter.setter
    def filter(self, value: Callable[[NoteVM], bool] | None) -> None:
        if value is self._filter:
            return
        self._filter = value
        self._recompute_filtered()

    def can_filter(self) -> bool:
        return self._status == ConstructionStatus.CONSTRUCTED

    @property
    def show_starred_only(self) -> bool:
        return self._show_starred_only

    @show_starred_only.setter
    def show_starred_only(self, value: bool) -> None:
        if self._show_starred_only == value:
            return
        self._show_starred_only = value
        self._notify_property_changed("show_starred_only")
        self._recompute_filtered()

    # ── Pageable ───────────────────────────────────────────────────────────
    @property
    def page_size(self) -> int:
        return self._paged.page_size

    @page_size.setter
    def page_size(self, value: int) -> None:
        self._paged.page_size = value

    @property
    def current_page_index(self) -> int:
        return self._paged.current_page_index

    @current_page_index.setter
    def current_page_index(self, value: int) -> None:
        self._paged.current_page_index = value

    @property
    def page_count(self) -> int:
        return self._paged.page_count

    @property
    def is_paging_enabled(self) -> bool:
        return self._paged.is_paging_enabled

    def move_to_first_page(self) -> None:
        self._paged.move_to_first_page()

    def move_to_previous_page(self) -> None:
        self._paged.move_to_previous_page()

    def move_to_next_page(self) -> None:
        self._paged.move_to_next_page()

    def move_to_last_page(self) -> None:
        self._paged.move_to_last_page()

    @property
    def move_to_first_page_command(self) -> RelayCommand:
        return self._move_to_first_page_command

    @property
    def move_to_previous_page_command(self) -> RelayCommand:
        return self._move_to_previous_page_command

    @property
    def move_to_next_page_command(self) -> RelayCommand:
        return self._move_to_next_page_command

    @property
    def move_to_last_page_command(self) -> RelayCommand:
        return self._move_to_last_page_command

    # ── Bind-to (async fetch) ──────────────────────────────────────────────
    async def bind_to_async(self, notebook_id: str) -> None:
        """Cancel any in-flight fetch, load notes for *notebook_id*, replace items.

        Edge-case backfill (rapid-selection concurrency): increments a
        per-call token before awaiting; on resume a stale token is discarded
        so the most-recent select wins. Parity with TS
        ``NotesViewVM.bindToAsync`` (``#activeBindingToken``).
        """
        self._active_binding_token += 1
        my_token = self._active_binding_token
        notes = await self._repo.load_notes(notebook_id)
        if my_token != self._active_binding_token:
            return  # superseded by a newer bind_to_async
        self._bound_notebook_id = notebook_id
        self._replace_items(notes)

    def _replace_items(self, notes: list[NoteModel]) -> None:
        # Dispose existing children.
        for prev in list(self._inner):
            prev.dispose()
        with self._inner.batch_update():
            while self._inner.count > 0:
                self._inner.remove_at(0)
            for n in notes:
                builder = (
                    NoteVM.builder()
                    .name(f"note:{n.id}")
                    .services(self.hub, self._dispatcher)
                    .model(n)
                    .on_close(lambda _vm: self._clear_current())
                    .on_delete(self._delete_note)
                    .on_save(self._save_note)
                )

                # Read the dialog service at confirm time, not at NoteVM
                # build time: the composition root late-binds the real
                # TextualDialogService after the App exists, and a
                # default-arg capture here froze the boot NullDialogService
                # (confirm -> False) into every NoteVM, making deletion
                # impossible (runtime behavior). A still-unbound
                # service falls back to proceed-unconfirmed, matching the
                # behavior when no service was attached at all.
                async def _confirm(_vm: NoteVM) -> bool:
                    ds = self._dialog_service
                    if ds is None:
                        return True
                    return await ds.confirm(
                        f"Delete “{_vm.title}”?",
                        title="Delete note",
                    )

                builder = builder.confirm_delete(_confirm)
                if self._notification_hub is not None:
                    builder = builder.notification_hub(self._notification_hub)
                vm = builder.build()
                vm.construct()
                self._inner.append(vm)
        self._current = None
        self._notify_property_changed("current")
        self._recompute_filtered()
        self._paged.move_to_first_page()

    def refresh_note(self, note: NoteModel) -> None:
        """Refresh the list row for *note* after an external update (save).

        Re-seats the persisted model into the matching :class:`NoteVM` and
        re-runs the combined filter so row labels, the starred filter, and
        search results reflect the saved values (rows otherwise kept their
        construction-time title/star).
        """
        for vm in self._inner:
            if vm.model.id == note.id:
                vm.model = note
                break
        else:
            return
        self._recompute_filtered()

    def _clear_current(self) -> None:
        self.current = None

    async def _delete_note(self, note: NoteVM) -> None:
        """Persist the deletion before mutating the live list mirror."""
        await self._repo.delete_note(note.model.id)
        for i in range(self._inner.count):
            if self._inner[i] is note:
                with self._inner.batch_update():
                    self._inner.remove_at(i)
                break
        if self._current is note:
            self._current = None
            self._notify_property_changed("current")
        self._recompute_filtered()
        note.dispose()

    async def _save_note(self, note: NoteVM) -> None:
        """Persist ``note`` and surface repository failure through the command."""
        await self._repo.save_note(note.model)

    # ── Combined filter pipeline ───────────────────────────────────────────
    def _recompute_filtered(self) -> None:
        term = self._search.search_term.lower()
        result: list[NoteVM] = []
        for n in self._inner:
            if self._show_starred_only and not n.model.starred:
                continue
            if self._filter is not None and not self._filter(n):
                continue
            if term:
                hay = " ".join((n.title, n.body, *n.tags)).lower()
                if term not in hay:
                    continue
            result.append(n)
        self._filtered = result
        # Re-push self into the subject so DerivedProperties recompute.
        self._self_subject.on_next(self)
        self._notify_property_changed("filtered_items")
        self._notify_property_changed("is_empty")
        self._notify_property_changed("visible_items")
        self._notify_property_changed("page_label")

    def _build_page_label(self) -> str:
        pages = max(1, self._paged.page_count)
        return f"Page {self._paged.current_page_index + 1} of {pages}"

    def _on_paged_changed(self, property_name: str) -> None:
        self._notify_property_changed(property_name)
        if property_name in {"current_page_index", "page_count", "page_size"}:
            # Push a fresh self emission so derived "page_label" recomputes.
            self._self_subject.on_next(self)
            self._notify_property_changed("page_label")
            self._notify_property_changed("visible_items")

    # ── Lifecycle override ─────────────────────────────────────────────────
    def _release_children(self) -> None:
        for prev in list(self._inner):
            prev.dispose()
        self._inner.clear()
        self._filtered = []
        self._current = None
        self._bound_notebook_id = None

    def _on_destruct(self) -> None:
        self._release_children()
        super()._on_destruct()

    def _on_dispose(self) -> None:
        self._release_children()
        self._paged.dispose()
        self._search.dispose()
        self._is_empty.dispose()
        self._page_label.dispose()
        self._self_subject.on_completed()
        self._self_subject.dispose()
        self._move_to_first_page_command.dispose()
        self._move_to_previous_page_command.dispose()
        self._move_to_next_page_command.dispose()
        self._move_to_last_page_command.dispose()
        super()._on_dispose()

    # ── Builder entry-point ────────────────────────────────────────────────
    @staticmethod
    def builder() -> NotesViewVMBuilder:  # type: ignore[override]
        # Narrows ComponentVM.builder() to the showcase NotesViewVMBuilder.
        return NotesViewVMBuilder()


# Filterable is Generic[T] — register at class level to avoid MRO conflict.
Filterable.register(NotesViewVM)


@dataclasses.dataclass(frozen=True, slots=True)
class NotesViewVMBuilder:
    """Immutable fluent builder for :class:`NotesViewVM`."""

    _name: str | None = None
    _hint: str = ""
    _hub: MessageHubProto[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _repo: INoteRepository | None = None
    _page_size: int = _DEFAULT_PAGE_SIZE
    _search_debounce_seconds: float = _DEFAULT_SEARCH_DEBOUNCE_S
    _search_scheduler: SchedulerBase | None = None
    _dialog_service: IDialogService | None = None
    _notification_hub: INotificationHub | None = None

    def name(self, value: str) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHubProto[Message], dispatcher: Dispatcher
    ) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def repository(self, repo: INoteRepository) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _repo=repo)

    def page_size(self, value: int) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _page_size=value)

    def search_debounce_seconds(self, value: float) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _search_debounce_seconds=value)

    def search_scheduler(self, scheduler: SchedulerBase) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _search_scheduler=scheduler)

    def dialog_service(self, service: IDialogService) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _dialog_service=service)

    def notification_hub(self, nh: INotificationHub) -> NotesViewVMBuilder:
        return dataclasses.replace(self, _notification_hub=nh)

    def build(self) -> NotesViewVM:
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
        return NotesViewVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            repository=self._repo,
            page_size=self._page_size,
            search_debounce_seconds=self._search_debounce_seconds,
            search_scheduler=self._search_scheduler,
            dialog_service=self._dialog_service,
            notification_hub=self._notification_hub,
        )
