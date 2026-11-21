"""COL-073 — a failing subscriber of a token-paging notification step skips no
later step of the committed load or refresh (spec/21 §6.2, ADR-0239, extends
ADR-0220).

The steps are the ``Reset`` event, the ``items``, ``current_token`` and
``has_more`` property notifications, and the command re-signal. The first
failure is re-raised to the caller after the last step. A subscriber that
disposes the composition stops the later steps.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.collections.token_paged_composition import TokenPagedComposition


class SubscriberError(Exception):
    """Raised by the failing subscriber."""


def _raise(_: object) -> None:
    raise SubscriberError


async def _terminal_page(_: str | None) -> tuple[list[str], str | None]:
    return (["x", "y"], None)


@pytest.mark.conformance("COL-073")
async def test_COL_073_failing_reset_subscriber_skips_no_later_step_on_load() -> None:
    sut: TokenPagedComposition[str, str] = TokenPagedComposition(_terminal_page)
    events: list[str] = []
    sut.on_collection_changed.subscribe(_raise)
    sut.on_collection_changed.subscribe(lambda event: events.append(f"collection:{event.action}"))
    sut.on_property_changed.subscribe(lambda name: events.append(f"property:{name}"))
    # The load command raises its own can_execute_changed when it starts and
    # finishes, so the trace observes the refresh command, which only the
    # composition's re-signal reaches during a load.
    sut.refresh_command.can_execute_changed.subscribe(
        lambda _: events.append("refresh:can_execute_changed")
    )

    with pytest.raises(SubscriberError):
        await sut.load_more_command.execute_async()

    assert sut.items == ["x", "y"]
    assert sut.has_more is False
    assert events == [
        "collection:reset",
        "property:items",
        "property:current_token",
        "property:has_more",
        "refresh:can_execute_changed",
    ]


@pytest.mark.conformance("COL-073")
async def test_COL_073_failing_reset_subscriber_skips_no_later_step_on_replacing_refresh() -> None:
    first_page: dict[str, tuple[list[str], str | None]] = {"page": (["a", "b"], "t2")}

    async def fetch(token: str | None) -> tuple[list[str], str | None]:
        return first_page["page"] if token is None else (["c"], None)

    sut: TokenPagedComposition[str, str] = TokenPagedComposition(fetch)
    await sut.load_more_command.execute_async()
    first_page["page"] = (["z"], None)

    events: list[str] = []
    sut.on_collection_changed.subscribe(_raise)
    sut.on_collection_changed.subscribe(lambda event: events.append(f"collection:{event.action}"))
    sut.on_property_changed.subscribe(lambda name: events.append(f"property:{name}"))
    sut.load_more_command.can_execute_changed.subscribe(
        lambda _: events.append("load_more:can_execute_changed")
    )

    with pytest.raises(SubscriberError):
        await sut.refresh_command.execute_async()

    assert sut.items == ["z"]
    assert sut.current_token is None
    assert sut.has_more is False
    assert events == [
        "collection:reset",
        "property:items",
        "property:current_token",
        "property:has_more",
        "load_more:can_execute_changed",
    ]


@pytest.mark.conformance("COL-073")
async def test_COL_073_failing_property_subscriber_skips_no_later_step() -> None:
    sut: TokenPagedComposition[str, str] = TokenPagedComposition(_terminal_page)
    names: list[str] = []
    re_signals: list[str] = []
    sut.on_property_changed.subscribe(_raise)
    sut.on_property_changed.subscribe(names.append)
    sut.refresh_command.can_execute_changed.subscribe(lambda _: re_signals.append("refresh"))

    with pytest.raises(SubscriberError):
        await sut.load_more_command.execute_async()

    assert names == ["items", "current_token", "has_more"]
    assert re_signals == ["refresh"]


@pytest.mark.conformance("COL-073")
async def test_COL_073_disposing_reset_subscriber_stops_the_later_steps() -> None:
    sut: TokenPagedComposition[str, str] = TokenPagedComposition(_terminal_page)
    names: list[str] = []
    re_signals: list[Any] = []
    sut.on_collection_changed.subscribe(lambda _: sut.dispose())
    sut.on_property_changed.subscribe(names.append)
    sut.refresh_command.can_execute_changed.subscribe(re_signals.append)

    await sut.load_more_command.execute_async()

    assert names == []
    assert re_signals == []
