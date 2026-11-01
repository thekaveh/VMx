"""GlobalSearchVM — token-paged all-notes search."""

from __future__ import annotations

import dataclasses
import threading

from reactivex.abc import SchedulerBase
from vmx import (
    AsyncRelayCommand,
    ComponentVM,
    MessageHub,
    MessageHubProto,
    RxDispatcher,
    SearchableState,
    TokenPagedComposition,
)
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher

from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.viewmodels.note_vm import NoteVM
from notes_showcase.viewmodels.notes_view_vm import default_search_scheduler

_DEFAULT_PAGE_SIZE = 5
_DEFAULT_SEARCH_DEBOUNCE_S = 0.150


@dataclasses.dataclass(frozen=True, slots=True)
class _SearchCursor:
    """The cursor for the next page. It keeps the term of the loaded pages."""

    term: str
    offset: str


class GlobalSearchVM(ComponentVM):
    """Token-paged search that owns every result VM it creates."""

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
    ) -> None:
        super().__init__(name=name, hint=hint, hub=hub, dispatcher=dispatcher)
        self._repo = repository
        self._page_size = page_size
        self._search = SearchableState[str](
            items=lambda: ["global-search"],
            predicate=lambda _item, _term: True,
            debounce_seconds=search_debounce_seconds,
            scheduler=search_scheduler
            or default_search_scheduler(dispatcher, search_debounce_seconds),
        )
        self._owned_results_lock = threading.Lock()
        self._owned_results: dict[int, NoteVM] = {}
        # The search term that fetched each owned result, by ``id``.
        self._result_terms: dict[int, str] = {}
        self._owned_results_disposed = False
        self._paged: TokenPagedComposition[NoteVM, _SearchCursor] = TokenPagedComposition(
            self._fetch_next,
            auto_construct_on_add=True,
            # Pages for different terms are never equal, so a refresh for a new
            # term replaces the loaded pages and their cursor.
            pages_equal=lambda left, right: (
                [self._result_key(n) for n in left] == [self._result_key(n) for n in right]
            ),
        )
        self._collection_sub = self._paged.on_collection_changed.subscribe(
            lambda _event: self._notify_results()
        )
        self._property_sub = self._paged.on_property_changed.subscribe(
            lambda name: self._notify_has_more() if name == "has_more" else None
        )
        # Latest term wins: the refresh command refuses to start while one is
        # in flight, so a term typed during a refresh would otherwise leave
        # results for the stale term on screen. ``_refresh_term`` is the term
        # of the latest first-page fetch. When a refresh settles for an older
        # term, refresh again for the current one.
        self._refresh_term: str | None = None
        self._refresh_settled_sub = self._paged.refresh_command.can_execute_changed.subscribe(
            lambda _: self._refresh_if_stale()
        )
        # A refresh replaces the loaded pages, so "Load more" is not available
        # until the refresh is complete. A call made during a refresh does
        # nothing. A load that starts during a refresh makes the composition
        # discard that refresh (spec 21 §6.2).
        self._load_more_command = (
            AsyncRelayCommand.builder()
            .predicate(
                lambda: (
                    self._paged.load_more_command.can_execute()
                    and not self._paged.refresh_command.is_executing
                )
            )
            .triggers(self._paged.load_more_command.can_execute_changed)
            .triggers(self._paged.refresh_command.can_execute_changed)
            .task(self._load_more_unless_refreshing)
            .build()
        )

    @property
    def search_term(self) -> str:
        return self._search.search_term

    @search_term.setter
    def search_term(self, value: str) -> None:
        if self._search.search_term == value:
            return
        self._search.search_term = value
        self._notify_property_changed("search_term")

    def can_search(self) -> bool:
        return self._search.can_search()

    def search(self) -> None:
        self._search.search()
        if not self.refresh_command.is_executing:
            self.refresh_command.execute()
        # Otherwise _refresh_if_stale re-runs it for the latest term once the
        # in-flight refresh settles.

    def _refresh_if_stale(self) -> None:
        command = self.refresh_command
        if (
            self._refresh_term is not None
            and self._refresh_term != self.search_term
            and not command.is_executing
            and command.can_execute()
        ):
            command.execute()

    @property
    def results(self) -> list[NoteVM]:
        return self._paged.items

    @property
    def has_more(self) -> bool:
        return self._paged.has_more

    @property
    def refresh_command(self) -> AsyncRelayCommand:
        return self._paged.refresh_command

    @property
    def load_more_command(self) -> AsyncRelayCommand:
        return self._load_more_command

    async def _fetch_next(
        self, cursor: _SearchCursor | None
    ) -> tuple[list[NoteVM], _SearchCursor | None]:
        # The first page uses the current term. A later page uses the term in
        # the cursor, so "Load more" continues the term of the loaded pages.
        if cursor is None:
            term, offset = self.search_term, None
            self._refresh_term = term
        else:
            term, offset = cursor.term, cursor.offset
        page, next_token = await self._repo.search_notes(term, offset, self._page_size)
        return (
            [
                self._own_result(
                    NoteVM.builder()
                    .name(f"global-{note.id}")
                    .services(self._hub, self._dispatcher)
                    .model(note)
                    .build(),
                    term,
                )
                for note in page
            ],
            None if next_token is None else _SearchCursor(term, next_token),
        )

    async def _load_more_unless_refreshing(self) -> None:
        # The task starts after the predicate passed. A refresh that starts in
        # that gap makes this load do nothing. A refresh that starts later
        # discards the load (spec 21 §6.2).
        if self._paged.refresh_command.is_executing:
            return
        await self._paged.load_more_command.execute_async()

    def _result_key(self, result: NoteVM) -> tuple[str, str | None]:
        with self._owned_results_lock:
            return result.model.id, self._result_terms.get(id(result))

    def _own_result(self, result: NoteVM, term: str) -> NoteVM:
        with self._owned_results_lock:
            dispose_immediately = self._owned_results_disposed
            if not dispose_immediately:
                self._owned_results[id(result)] = result
                self._result_terms[id(result)] = term
        if dispose_immediately:
            result.dispose()
        return result

    def _dispose_owned_results(self) -> None:
        with self._owned_results_lock:
            self._owned_results_disposed = True
            owned = list(self._owned_results.values())
            self._owned_results.clear()
            self._result_terms.clear()
        for result in owned:
            result.dispose()

    def _notify_results(self) -> None:
        self._notify_property_changed("results")

    def _notify_has_more(self) -> None:
        self._notify_property_changed("has_more")

    def dispose(self) -> None:
        self._collection_sub.dispose()
        self._property_sub.dispose()
        self._refresh_settled_sub.dispose()
        self._dispose_owned_results()
        self._load_more_command.dispose()
        self._paged.dispose()
        self._search.dispose()
        super().dispose()

    @staticmethod
    def builder() -> GlobalSearchVMBuilder:  # type: ignore[override]
        return GlobalSearchVMBuilder()


@dataclasses.dataclass(frozen=True, slots=True)
class GlobalSearchVMBuilder:
    _name: str | None = None
    _hint: str = ""
    _hub: MessageHubProto[Message] | None = None
    _dispatcher: Dispatcher | None = None
    _repo: INoteRepository | None = None
    _page_size: int = _DEFAULT_PAGE_SIZE
    _search_debounce_seconds: float = _DEFAULT_SEARCH_DEBOUNCE_S
    _search_scheduler: SchedulerBase | None = None

    def name(self, value: str) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _name=value)

    def hint(self, value: str) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _hint=value)

    def services(
        self, hub: MessageHubProto[Message], dispatcher: Dispatcher
    ) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _hub=hub, _dispatcher=dispatcher)

    def repository(self, repo: INoteRepository) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _repo=repo)

    def page_size(self, value: int) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _page_size=value)

    def search_debounce_seconds(self, value: float) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _search_debounce_seconds=value)

    def search_scheduler(self, scheduler: SchedulerBase) -> GlobalSearchVMBuilder:
        return dataclasses.replace(self, _search_scheduler=scheduler)

    def build(self) -> GlobalSearchVM:
        if self._name is None:
            raise ValueError("name is required")
        hub = self._hub if self._hub is not None else MessageHub[Message]()
        dispatcher = self._dispatcher if self._dispatcher is not None else RxDispatcher.immediate()
        if self._repo is None:
            raise ValueError("repository is required")
        return GlobalSearchVM(
            name=self._name,
            hint=self._hint,
            hub=hub,
            dispatcher=dispatcher,
            repository=self._repo,
            page_size=self._page_size,
            search_debounce_seconds=self._search_debounce_seconds,
            search_scheduler=self._search_scheduler,
        )
