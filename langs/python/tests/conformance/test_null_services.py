"""Conformance tests: NULL-001..003 — null-object service convention.

Per spec/03-messages.md §"Null variant", spec/11-threading.md §"Null variant",
and ADR-0017.
"""

from __future__ import annotations

import pytest
from reactivex.abc import SchedulerBase

from vmx import (
    NULL_DISPATCHER,
    NULL_MESSAGE_HUB,
    ConstructionStatusChangedMessage,
    NullDispatcher,
    NullMessageHub,
)
from vmx.lifecycle import ConstructionStatus

# ---------------------------------------------------------------------------
# NULL-001 — NullMessageHub is a safe no-op
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NULL-001")
def test_NULL_001_nullmessagehub_is_safe_noop() -> None:
    hub = NULL_MESSAGE_HUB
    observed: list[object] = []
    completed = False

    def _on_next(m: object) -> None:
        observed.append(m)

    def _on_completed() -> None:
        nonlocal completed
        completed = True

    sub = hub.messages.subscribe(on_next=_on_next, on_completed=_on_completed)
    try:
        for _ in range(5):
            hub.send(
                ConstructionStatusChangedMessage.create(
                    object(), "x", ConstructionStatus.CONSTRUCTED
                )
            )
        body_ran = False
        with hub.batch():
            body_ran = True
            hub.send(
                ConstructionStatusChangedMessage.create(
                    object(), "x", ConstructionStatus.CONSTRUCTED
                )
            )
        assert observed == []
        assert completed is True
        assert body_ran is True
    finally:
        sub.dispose()


# ---------------------------------------------------------------------------
# NULL-002 — NullDispatcher schedules synchronously on the calling thread
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NULL-002")
def test_NULL_002_nulldispatcher_schedules_synchronously() -> None:
    dispatcher = NULL_DISPATCHER
    foreground_ran = False
    background_ran = False

    def _fg(_scheduler: SchedulerBase, _state: object) -> None:
        nonlocal foreground_ran
        foreground_ran = True

    def _bg(_scheduler: SchedulerBase, _state: object) -> None:
        nonlocal background_ran
        background_ran = True

    dispatcher.foreground.schedule(_fg)
    assert foreground_ran is True

    dispatcher.background.schedule(_bg)
    assert background_ran is True


# ---------------------------------------------------------------------------
# NULL-003 — Null-object convention satisfied for every core service contract
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NULL-003")
def test_NULL_003_null_convention_satisfied() -> None:
    # MessageHubProto → NullMessageHub
    assert hasattr(NullMessageHub, "__init__")
    hub = NullMessageHub()
    # send must be total (no input raises)
    hub.send(ConstructionStatusChangedMessage.create(object(), "x", ConstructionStatus.CONSTRUCTED))
    _ = hub.messages

    # Dispatcher Protocol → NullDispatcher
    assert hasattr(NullDispatcher, "__init__")
    dispatcher = NullDispatcher()
    assert dispatcher.foreground is not None
    assert dispatcher.background is not None
