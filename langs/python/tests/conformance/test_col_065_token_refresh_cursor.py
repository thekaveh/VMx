"""Conformance tests: COL-065 — a token-paged refresh keeps ``items`` and
``current_token`` describing one loaded prefix (spec 21 §6.2, ADR-0136)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from vmx.collections.token_paged_composition import TokenPagedComposition
from vmx.components.component_vm import ComponentVM
from vmx.lifecycle.status import ConstructionStatus

Page = tuple[list[int], str | None]

PAGES: dict[str, Page] = {
    "t2": ([3, 4], "t3"),
    "t3": ([5, 6], "t4"),
    "t4": ([7], None),
}


class Backend:
    """First page can change between calls; later pages are keyed by token."""

    def __init__(self) -> None:
        self.requested: list[str | None] = []
        self.first_page: Page = ([1, 2], "t2")
        self.error: Exception | None = None

    async def fetch(self, token: str | None) -> Page:
        self.requested.append(token)
        if self.error is not None:
            raise self.error
        return self.first_page if token is None else PAGES[token]


async def _load(sut: TokenPagedComposition[int, str], count: int) -> None:
    for _ in range(count):
        await sut.load_more_command.execute_async()


async def _until_pending(pending: list[asyncio.Future[Page]], count: int) -> None:
    for _ in range(100):
        if len(pending) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} pending fetches, saw {len(pending)}")


def _trace(sut: TokenPagedComposition[int, str]) -> list[str]:
    trace: list[str] = []
    sut.on_collection_changed.subscribe(lambda event: trace.append(f"collection:{event.action}"))
    sut.on_property_changed.subscribe(lambda name: trace.append(f"property:{name}"))
    sut.load_more_command.can_execute_changed.subscribe(
        lambda _: trace.append("load_more:can_execute_changed")
    )
    return trace


@pytest.mark.conformance("COL-065")
async def test_COL_065_unchanged_head_refresh_keeps_cursor_so_load_more_never_refetches() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 3)

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2, 3, 4, 5, 6]
    assert sut.current_token == "t4"
    assert sut.has_more is True

    await sut.load_more_command.execute_async()

    assert sut.items == [1, 2, 3, 4, 5, 6, 7]
    assert api.requested == [None, "t2", "t3", None, "t4"]
    assert sut.current_token is None
    assert sut.has_more is False


@pytest.mark.conformance("COL-065")
async def test_shorter_matching_non_terminal_head_keeps_accumulator_and_cursor() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.first_page = ([1], "u1")

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2, 3, 4]
    assert sut.current_token == "t3"


@pytest.mark.conformance("COL-065")
async def test_unchanged_single_page_adopts_a_changed_opaque_token_without_reset() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 1)
    api.first_page = ([1, 2], "fresh-t2")
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2]
    assert sut.current_token == "fresh-t2"
    assert "collection:reset" not in trace


@pytest.mark.conformance("COL-065")
async def test_unchanged_single_page_adopts_a_newly_terminal_token() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 1)
    api.first_page = ([1, 2], None)

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2]
    assert sut.current_token is None
    assert sut.has_more is False
    assert sut.load_more_command.can_execute() is False


@pytest.mark.conformance("COL-065")
async def test_changed_head_replaces_accumulator_and_adopts_refreshed_token() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.first_page = ([9, 2], "u2")
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert sut.items == [9, 2]
    assert sut.current_token == "u2"
    assert trace.count("collection:reset") == 1


@pytest.mark.conformance("COL-065")
async def test_terminal_first_page_shorter_than_accumulator_replaces_it() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.first_page = ([1, 2], None)

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2]
    assert sut.current_token is None
    assert sut.has_more is False


@pytest.mark.conformance("COL-065")
async def test_empty_terminal_first_page_clears_a_non_empty_accumulator() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.first_page = ([], None)
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert sut.items == []
    assert sut.current_token is None
    assert sut.has_more is False
    assert "collection:reset" in trace


@pytest.mark.conformance("COL-065")
async def test_empty_first_page_with_continuation_replaces_and_adopts_token() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.first_page = ([], "u1")

    await sut.refresh_command.execute_async()

    assert sut.items == []
    assert sut.current_token == "u1"
    assert sut.has_more is True


@pytest.mark.conformance("COL-065")
async def test_refresh_after_reaching_the_end_keeps_the_terminal_cursor() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 4)
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert sut.items == [1, 2, 3, 4, 5, 6, 7]
    assert sut.current_token is None
    assert sut.has_more is False
    assert sut.load_more_command.can_execute() is False
    assert "collection:reset" not in trace


@pytest.mark.conformance("COL-065")
async def test_no_mutation_branch_publishes_properties_then_command_signal() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 3)
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert trace == [
        "property:items",
        "property:current_token",
        "property:has_more",
        "load_more:can_execute_changed",
    ]


@pytest.mark.conformance("COL-065")
async def test_replacement_branch_publishes_reset_properties_then_command_signal() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 3)
    api.first_page = ([8, 9], "u2")
    trace = _trace(sut)

    await sut.refresh_command.execute_async()

    assert trace == [
        "collection:reset",
        "property:items",
        "property:current_token",
        "property:has_more",
        "load_more:can_execute_changed",
    ]


async def test_load_started_during_refresh_makes_the_refresh_result_stale() -> None:
    loop = asyncio.get_running_loop()
    pending: list[asyncio.Future[Page]] = []
    requested: list[str | None] = []

    async def fetch(token: str | None) -> Page:
        requested.append(token)
        future: asyncio.Future[Page] = loop.create_future()
        pending.append(future)
        return await future

    sut = TokenPagedComposition(fetch_next=fetch)
    first = asyncio.ensure_future(sut.load_more_command.execute_async())
    await _until_pending(pending, 1)
    pending[0].set_result(([1, 2], "t2"))
    await first

    refresh = asyncio.ensure_future(sut.refresh_command.execute_async())
    await _until_pending(pending, 2)
    load = asyncio.ensure_future(sut.load_more_command.execute_async())
    await _until_pending(pending, 3)
    pending[1].set_result(([9], "stale"))
    await refresh
    pending[2].set_result(([3, 4], "t3"))
    await load

    assert requested == [None, None, "t2"]
    assert sut.items == [1, 2, 3, 4]
    assert sut.current_token == "t3"


async def test_failed_refresh_fetch_leaves_items_cursor_and_notifications_untouched() -> None:
    api = Backend()
    sut = TokenPagedComposition(fetch_next=api.fetch)
    await _load(sut, 2)
    api.error = RuntimeError("offline")
    trace = _trace(sut)

    with pytest.raises(RuntimeError, match="offline"):
        await sut.refresh_command.execute_async()

    assert sut.items == [1, 2, 3, 4]
    assert sut.current_token == "t3"
    assert trace == []
    assert sut.refresh_command.is_executing is False


async def test_throwing_page_comparer_leaves_items_cursor_and_notifications_untouched() -> None:
    api = Backend()
    fail = False

    def pages_equal(left: Sequence[int], right: Sequence[int]) -> bool:
        if fail:
            raise RuntimeError("comparer failed")
        return list(left) == list(right)

    sut = TokenPagedComposition(fetch_next=api.fetch, pages_equal=pages_equal)
    await _load(sut, 2)
    fail = True
    trace = _trace(sut)

    with pytest.raises(RuntimeError, match="comparer failed"):
        await sut.refresh_command.execute_async()

    assert sut.items == [1, 2, 3, 4]
    assert sut.current_token == "t3"
    assert trace == []


async def test_disposal_before_retained_prefix_refresh_completes_leaves_state_untouched() -> None:
    api = Backend()
    loop = asyncio.get_running_loop()
    held: asyncio.Future[Page] = loop.create_future()
    hold = False

    async def fetch(token: str | None) -> Page:
        if hold:
            return await held
        return await api.fetch(token)

    sut = TokenPagedComposition(fetch_next=fetch)
    await _load(sut, 2)
    hold = True
    trace = _trace(sut)

    refresh = asyncio.ensure_future(sut.refresh_command.execute_async())
    await asyncio.sleep(0)
    sut.dispose()
    held.set_result(([1, 2], "t2"))
    await refresh

    assert sut.items == [1, 2, 3, 4]
    assert sut.current_token == "t3"
    assert trace == []


async def test_retained_and_replaced_item_vms_are_never_disposed_by_the_composition() -> None:
    def vm(name: str) -> ComponentVM:
        return ComponentVM.builder().name(name).with_null_services().build()

    loaded = [vm("a"), vm("b"), vm("c"), vm("d")]
    equal_head = [vm("a"), vm("b")]
    changed_head = [vm("x"), vm("y")]
    refresh_page = equal_head
    first_load = True

    async def fetch(token: str | None) -> tuple[list[ComponentVM], str | None]:
        nonlocal first_load
        if token is None:
            if first_load:
                first_load = False
                return loaded[:2], "t2"
            return refresh_page, "t2"
        return loaded[2:], "t3"

    sut = TokenPagedComposition(
        fetch_next=fetch,
        auto_construct_on_add=True,
        pages_equal=lambda left, right: (
            [item.name for item in left] == [item.name for item in right]
        ),
    )
    await sut.load_more_command.execute_async()
    await sut.load_more_command.execute_async()

    await sut.refresh_command.execute_async()

    assert sut.items == loaded
    assert sut.current_token == "t3"
    assert [item.status for item in equal_head] == [ConstructionStatus.DESTRUCTED] * 2

    refresh_page = changed_head
    await sut.refresh_command.execute_async()

    assert sut.items == changed_head
    assert all(item.is_constructed for item in changed_head)
    assert all(item.status is ConstructionStatus.CONSTRUCTED for item in loaded)
