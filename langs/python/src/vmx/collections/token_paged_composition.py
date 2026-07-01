"""TokenPagedComposition — accumulated, forward-only token pagination."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.commands.async_relay_command import AsyncRelayCommand
from vmx.components.base import _ComponentVMBase

TVM = TypeVar("TVM")
TToken = TypeVar("TToken")

FetchNext = Callable[[TToken | None], Awaitable[tuple[Sequence[TVM], TToken | None]]]
PagesEqual = Callable[[Sequence[TVM], Sequence[TVM]], bool]


class TokenPagedComposition(Generic[TVM, TToken]):
    """Accumulates pages fetched by an opaque forward-only token."""

    def __init__(
        self,
        fetch_next: FetchNext[TToken, TVM],
        *,
        auto_construct_on_add: bool = False,
        pages_equal: PagesEqual[TVM] | None = None,
    ) -> None:
        self._fetch_next = fetch_next
        self._auto_construct_on_add = auto_construct_on_add
        self._pages_equal = pages_equal or (lambda left, right: list(left) == list(right))
        self._items: list[TVM] = []
        self._current_token: TToken | None = None
        self._loaded_once = False
        self._disposed = False
        self._collection_changed: Subject[CollectionChangedEvent] = Subject()
        self._property_changed: Subject[str] = Subject()
        self._command_changed: Subject[None] = Subject()
        self._load_more_command = (
            AsyncRelayCommand.builder()
            .predicate(lambda: self.has_more and not self._disposed)
            .triggers(self._command_changed)
            .task(self._load_more)
            .build()
        )
        self._refresh_command = (
            AsyncRelayCommand.builder()
            .predicate(lambda: not self._disposed)
            .triggers(self._command_changed)
            .task(self._refresh)
            .build()
        )

    @property
    def items(self) -> list[TVM]:
        return list(self._items)

    @property
    def current_token(self) -> TToken | None:
        return self._current_token

    @property
    def has_more(self) -> bool:
        return not self._loaded_once or self._current_token is not None

    @property
    def load_more_command(self) -> AsyncRelayCommand:
        return self._load_more_command

    @property
    def refresh_command(self) -> AsyncRelayCommand:
        return self._refresh_command

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedEvent]:
        return self._collection_changed.pipe(ops.as_observable())

    @property
    def on_property_changed(self) -> rx.Observable[str]:
        return self._property_changed.pipe(ops.as_observable())

    async def _load_more(self) -> None:
        page, next_token = await self._fetch_next(self._current_token)
        if self._disposed:
            return
        additions = list(page)
        self._items.extend(additions)
        self._construct_if_needed(additions)
        self._current_token = next_token
        self._loaded_once = True
        self._notify_reset()

    async def _refresh(self) -> None:
        page, next_token = await self._fetch_next(None)
        if self._disposed:
            return
        fresh = list(page)
        if self._pages_equal(fresh, self._items[: len(fresh)]):
            self._current_token = next_token
            self._loaded_once = True
            self._notify_properties()
            return
        self._items = fresh
        self._construct_if_needed(fresh)
        self._current_token = next_token
        self._loaded_once = True
        self._notify_reset()

    def _construct_if_needed(self, items: Sequence[TVM]) -> None:
        if not self._auto_construct_on_add:
            return
        for item in items:
            if isinstance(item, _ComponentVMBase) and not item.is_constructed:
                item.construct()

    def _notify_reset(self) -> None:
        self._collection_changed.on_next(CollectionChangedEvent(action="reset"))
        self._notify_properties()

    def _notify_properties(self) -> None:
        for name in ("items", "current_token", "has_more"):
            self._property_changed.on_next(name)
        self._command_changed.on_next(None)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._load_more_command.dispose()
        self._refresh_command.dispose()
        self._collection_changed.on_completed()
        self._collection_changed.dispose()
        self._property_changed.on_completed()
        self._property_changed.dispose()
        self._command_changed.on_completed()
        self._command_changed.dispose()
