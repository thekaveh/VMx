"""GlobalSearchVM — token-paged all-notes search."""

from __future__ import annotations

import dataclasses
import threading

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ImmediateScheduler

from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.viewmodels.note_vm import NoteVM
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

_DEFAULT_PAGE_SIZE = 5
_DEFAULT_SEARCH_DEBOUNCE_S = 0.150


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
            scheduler=search_scheduler or ImmediateScheduler(),
        )
        self._owned_results_lock = threading.Lock()
        self._owned_results: dict[int, NoteVM] = {}
        self._owned_results_disposed = False
        self._paged: TokenPagedComposition[NoteVM, str] = TokenPagedComposition(
            self._fetch_next,
            auto_construct_on_add=True,
            pages_equal=lambda left, right: (
                [n.model.id for n in left] == [n.model.id for n in right]
            ),
        )
        self._collection_sub = self._paged.on_collection_changed.subscribe(
            lambda _event: self._notify_results()
        )
        self._property_sub = self._paged.on_property_changed.subscribe(
            lambda name: self._notify_has_more() if name == "has_more" else None
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
        self.refresh_command.execute()

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
        return self._paged.load_more_command

    async def _fetch_next(self, token: str | None) -> tuple[list[NoteVM], str | None]:
        page, next_token = await self._repo.search_notes(
            self.search_term, token, self._page_size
        )
        return (
            [
                self._own_result(
                    NoteVM.builder()
                    .name(f"global-{note.id}")
                    .services(self._hub, self._dispatcher)
                    .model(note)
                    .build()
                )
                for note in page
            ],
            next_token,
        )

    def _own_result(self, result: NoteVM) -> NoteVM:
        with self._owned_results_lock:
            dispose_immediately = self._owned_results_disposed
            if not dispose_immediately:
                self._owned_results[id(result)] = result
        if dispose_immediately:
            result.dispose()
        return result

    def _dispose_owned_results(self) -> None:
        with self._owned_results_lock:
            self._owned_results_disposed = True
            owned = list(self._owned_results.values())
            self._owned_results.clear()
        for result in owned:
            result.dispose()

    def _notify_results(self) -> None:
        self._notify_property_changed("results")

    def _notify_has_more(self) -> None:
        self._notify_property_changed("has_more")

    def dispose(self) -> None:
        self._collection_sub.dispose()
        self._property_sub.dispose()
        self._dispose_owned_results()
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
        dispatcher = (
            self._dispatcher
            if self._dispatcher is not None
            else RxDispatcher.immediate()
        )
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
