"""Conformance tests: COL-024..COL-031 — token pagination and composite source paging."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from tests.liveness import HANG_GUARD
from vmx.collections.paged_composition import PagedComposition
from vmx.collections.token_paged_composition import TokenPagedComposition
from vmx.components.component_vm import ComponentVM
from vmx.composites.composite_vm import CompositeVM
from vmx.services.null_dispatcher import NULL_DISPATCHER
from vmx.services.null_message_hub import NULL_MESSAGE_HUB


@pytest.mark.conformance("COL-024")
def test_COL_024_token_paged_initial_state() -> None:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1, 2], "next") if token is None else ([], None)

    sut = TokenPagedComposition(fetch_next=fetch)

    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is True
    assert sut.load_more_command.can_execute() is True


@pytest.mark.conformance("COL-025")
async def test_COL_025_load_more_appends_items_and_advances_token() -> None:
    calls: list[str | None] = []

    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        calls.append(token)
        return ([1, 2], "two") if token is None else ([3], None)

    sut = TokenPagedComposition(fetch_next=fetch)

    await sut.load_more_command.execute_async()
    assert sut.items == [1, 2]
    assert sut.current_token == "two"
    assert sut.has_more is True

    await sut.load_more_command.execute_async()
    assert sut.items == [1, 2, 3]
    assert sut.current_token is None
    assert sut.has_more is False
    assert calls == [None, "two"]


async def test_load_more_does_not_mutate_or_notify_when_disposed_during_fetch() -> None:
    page: asyncio.Future[tuple[list[int], str | None]] = asyncio.Future()

    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return await page

    sut = TokenPagedComposition(fetch_next=fetch)
    collection_events: list[object] = []
    property_events: list[str] = []
    sut.on_collection_changed.subscribe(collection_events.append)
    sut.on_property_changed.subscribe(property_events.append)

    load = asyncio.create_task(sut.load_more_command.execute_async())
    await asyncio.sleep(0)
    sut.dispose()
    page.set_result(([1, 2], "next"))
    await load

    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is True
    assert collection_events == []
    assert property_events == []


async def test_auto_construct_reentrant_dispose_does_not_commit_or_fault() -> None:
    sut: TokenPagedComposition[ComponentVM, str] | None = None

    def dispose_pager() -> None:
        assert sut is not None
        sut.dispose()

    child = (
        ComponentVM.builder().name("child").with_null_services().on_construct(dispose_pager).build()
    )

    async def fetch(token: str | None) -> tuple[list[ComponentVM], str | None]:
        return ([child], "next")

    sut = TokenPagedComposition(fetch_next=fetch, auto_construct_on_add=True)
    collection_events: list[object] = []
    property_events: list[str] = []
    sut.on_collection_changed.subscribe(collection_events.append)
    sut.on_property_changed.subscribe(property_events.append)

    await sut.load_more_command.execute_async()

    assert child.is_constructed is True
    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is True
    assert collection_events == []
    assert property_events == []


@pytest.mark.conformance("COL-026")
async def test_COL_026_terminal_token_disables_load_more() -> None:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1], None)

    sut = TokenPagedComposition(fetch_next=fetch)

    await sut.load_more_command.execute_async()

    assert sut.has_more is False
    assert sut.load_more_command.can_execute() is False


class _TerminalAfterAdmissionHarness:
    """Pages [1] and [101] load, then a held refresh returns the terminal page.

    Regression harness for #1161 (spec 21 §6.2, ADR-0169): a load admitted while
    ``has_more`` is True must fetch nothing when a terminal token has landed by
    the time its body starts.
    """

    def __init__(self) -> None:
        self.calls: list[str | None] = []
        self.refresh_page: asyncio.Future[tuple[list[int], str | None]] | None = None
        self.held: asyncio.Future[tuple[list[int], str | None]] | None = None
        self.refresh_entered = asyncio.Event()
        self.resets = 0
        self.sut: TokenPagedComposition[int, str] = TokenPagedComposition(fetch_next=self.fetch)
        self.sut.on_collection_changed.subscribe(lambda _event: self._count_reset())

    def _count_reset(self) -> None:
        self.resets += 1

    async def fetch(self, token: str | None) -> tuple[list[int], str | None]:
        self.calls.append(token)
        if token is None and self.refresh_page is not None:
            page = self.refresh_page
            self.refresh_page = None
            self.refresh_entered.set()
            return await page
        if token is None:
            # Page 1. Before the fix a gated-out load refetched it here.
            return ([1], "1")
        return ([101], "2")

    async def load_two_pages(self) -> None:
        await asyncio.wait_for(self.sut.load_more_command.execute_async(), HANG_GUARD)
        await asyncio.wait_for(self.sut.load_more_command.execute_async(), HANG_GUARD)
        assert self.sut.items == [1, 101]
        assert self.sut.current_token == "2"

    async def start_held_refresh(self) -> asyncio.Task[None]:
        self.held = asyncio.get_running_loop().create_future()
        self.refresh_page = self.held
        refresh = asyncio.create_task(self.sut.refresh_command.execute_async())
        await asyncio.wait_for(self.refresh_entered.wait(), HANG_GUARD)
        self.resets = 0
        return refresh

    async def wait_idle(self) -> None:
        async def idle() -> None:
            while self.sut.load_more_command.is_executing or self.sut.refresh_command.is_executing:
                await asyncio.sleep(0)

        await asyncio.wait_for(idle(), HANG_GUARD)

    def assert_single_terminal_prefix(self, calls_before_commit: int) -> None:
        assert self.sut.items == [1, 101, 555]
        assert self.sut.current_token is None
        assert self.sut.has_more is False
        # Only the refresh fetched; the gated-out load fetched nothing.
        assert self.calls[calls_before_commit:] == [None]
        assert self.resets == 1


@pytest.mark.conformance("COL-026")
async def test_COL_026_execute_in_the_tick_a_terminal_refresh_lands_fetches_nothing() -> None:
    harness = _TerminalAfterAdmissionHarness()
    await harness.load_two_pages()
    calls_before_commit = len(harness.calls)
    refresh = await harness.start_held_refresh()
    future = harness.held
    assert future is not None

    # The refresh resumes before the scheduled load body runs.
    future.set_result(([1, 101, 555], None))
    assert harness.sut.load_more_command.can_execute() is True
    harness.sut.load_more_command.execute()

    await asyncio.wait_for(refresh, HANG_GUARD)
    await harness.wait_idle()
    harness.assert_single_terminal_prefix(calls_before_commit)


@pytest.mark.conformance("COL-026")
async def test_COL_026_execute_async_admitted_before_a_terminal_refresh_fetches_nothing() -> None:
    harness = _TerminalAfterAdmissionHarness()
    await harness.load_two_pages()
    calls_before_commit = len(harness.calls)
    refresh = await harness.start_held_refresh()
    future = harness.held
    assert future is not None

    # The load task is admitted first; the refresh commits before its body starts.
    load = asyncio.create_task(harness.sut.load_more_command.execute_async())
    future.set_result(([1, 101, 555], None))

    await asyncio.wait_for(load, HANG_GUARD)
    await asyncio.wait_for(refresh, HANG_GUARD)
    await harness.wait_idle()
    harness.assert_single_terminal_prefix(calls_before_commit)


@pytest.mark.conformance("COL-027")
async def test_COL_027_refresh_clears_and_refetches_first_page() -> None:
    pages = [([1, 2], "next"), ([9], None)]

    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        assert token is None
        return pages.pop(0)

    sut = TokenPagedComposition(fetch_next=fetch)

    await sut.load_more_command.execute_async()
    await sut.refresh_command.execute_async()

    assert sut.items == [9]
    assert sut.current_token is None
    assert sut.has_more is False


async def test_refresh_supersedes_an_older_in_flight_load_more() -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    calls = 0

    async def fetch(token: str | None) -> tuple[list[str], str | None]:
        nonlocal calls
        index = calls
        calls += 1
        entered[index].set()
        await release[index].wait()
        return ([f"page-{index}"], f"token-{index}")

    sut = TokenPagedComposition(fetch_next=fetch)
    load = asyncio.create_task(sut.load_more_command.execute_async())
    await asyncio.wait_for(entered[0].wait(), HANG_GUARD)

    refresh = asyncio.create_task(sut.refresh_command.execute_async())
    await asyncio.wait_for(entered[1].wait(), HANG_GUARD)
    release[1].set()
    await asyncio.wait_for(refresh, HANG_GUARD)
    assert sut.items == ["page-1"]

    release[0].set()
    await asyncio.wait_for(load, HANG_GUARD)

    assert sut.items == ["page-1"]
    assert sut.current_token == "token-1"


async def test_refresh_does_not_mutate_or_notify_when_disposed_during_fetch() -> None:
    page: asyncio.Future[tuple[list[int], str | None]] = asyncio.Future()

    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return await page

    sut = TokenPagedComposition(fetch_next=fetch)
    collection_events: list[object] = []
    property_events: list[str] = []
    sut.on_collection_changed.subscribe(collection_events.append)
    sut.on_property_changed.subscribe(property_events.append)

    refresh = asyncio.create_task(sut.refresh_command.execute_async())
    await asyncio.sleep(0)
    sut.dispose()
    page.set_result(([9], None))
    await refresh

    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is True
    assert collection_events == []
    assert property_events == []


async def test_refresh_comparer_reentrant_dispose_does_not_commit_or_fault() -> None:
    sut: TokenPagedComposition[int, str] | None = None

    def pages_equal(left: Sequence[int], right: Sequence[int]) -> bool:
        assert sut is not None
        sut.dispose()
        return left == right

    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1], "next")

    sut = TokenPagedComposition(fetch_next=fetch, pages_equal=pages_equal)

    await sut.refresh_command.execute_async()

    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is True


@pytest.mark.conformance("COL-028")
async def test_COL_028_refresh_dedup_guard_suppresses_redundant_mutation() -> None:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1, 2], "next")

    sut = TokenPagedComposition(fetch_next=fetch)
    seen: list[object] = []
    sut.on_collection_changed.subscribe(seen.append)

    await sut.load_more_command.execute_async()
    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2]
    assert len(seen) == 1


@pytest.mark.conformance("COL-029")
async def test_COL_029_token_paged_collection_changed_events_use_reset() -> None:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1, 2], None)

    sut = TokenPagedComposition(fetch_next=fetch)
    actions: list[str] = []
    sut.on_collection_changed.subscribe(lambda e: actions.append(e.action))

    await sut.load_more_command.execute_async()

    assert actions == ["reset"]


async def test_collection_observer_reentrant_dispose_stops_later_notifications() -> None:
    async def fetch(token: str | None) -> tuple[list[int], str | None]:
        return ([1], None)

    sut = TokenPagedComposition(fetch_next=fetch)
    property_events: list[str] = []
    sut.on_collection_changed.subscribe(lambda _: sut.dispose())
    sut.on_property_changed.subscribe(property_events.append)

    await sut.load_more_command.execute_async()

    assert sut.items == [1]
    assert property_events == []


@pytest.mark.conformance("COL-030")
async def test_COL_030_token_paged_auto_constructs_added_component_vms() -> None:
    child = ComponentVM.builder().name("child").with_null_services().build()

    async def fetch(token: str | None) -> tuple[list[ComponentVM], str | None]:
        return ([child], None)

    sut = TokenPagedComposition(fetch_next=fetch, auto_construct_on_add=True)
    constructed_at_reset: list[bool] = []
    sut.on_collection_changed.subscribe(
        lambda e: constructed_at_reset.append(child.is_constructed) if e.action == "reset" else None
    )

    await sut.load_more_command.execute_async()

    assert constructed_at_reset, "subscribers must observe the reset event"
    assert constructed_at_reset == [True] * len(constructed_at_reset), (
        "added component VMs are constructed before subscribers observe the reset"
    )
    assert child.is_constructed is True


@pytest.mark.conformance("COL-031")
def test_COL_031_paged_composition_observes_composite_collection_changes() -> None:
    composite: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("source")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: [])
        .build()
    )
    sut = PagedComposition(composite, page_size=2)
    seen: list[str] = []
    sut.on_property_changed.subscribe(seen.append)

    composite.add(ComponentVM.builder().name("a").with_null_services().build())

    assert sut.page_count == 1
    assert "items" in seen
