"""Conformance tests: COL-001..COL-004 — ServicedObservableCollection[T].

Per spec/21-collections.md §2 and ADR-0024.
"""

from __future__ import annotations

import threading

import pytest

from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[CollectionChangedMessage[str]]:
    return MessageHub()


# ---------------------------------------------------------------------------
# COL-001 — publish to hub after local event on add
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-001")
def test_COL_001_publishes_to_hub_after_local_event_on_add() -> None:
    """COL-001: ServicedObservableCollection publishes to hub after local CollectionChanged."""
    hub: MessageHub[CollectionChangedMessage[str]] = _hub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection(name="sut", hub=hub)

    local_events: list[CollectionChangedMessage[str]] = []
    hub_messages: list[CollectionChangedMessage[str]] = []

    sut.on_collection_changed.subscribe(local_events.append)
    hub.messages.subscribe(hub_messages.append)  # type: ignore[arg-type]

    sut.append("alpha")

    # Local event
    assert len(local_events) == 1
    assert local_events[0].action == "add"
    assert local_events[0].new_items == ("alpha",)
    assert local_events[0].index == 0

    # Hub message
    assert len(hub_messages) == 1
    msg = hub_messages[0]
    assert isinstance(msg, CollectionChangedMessage)
    assert msg.action == "add"
    assert msg.new_items == ("alpha",)
    assert msg.index == 0
    assert msg.sender_name == "sut"


# ---------------------------------------------------------------------------
# COL-002 — publish on remove and replace
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-002")
def test_COL_002_publishes_on_remove_and_replace() -> None:
    """COL-002: ServicedObservableCollection publishes correct messages on remove and replace."""
    hub: MessageHub[CollectionChangedMessage[str]] = _hub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection(name="sut", hub=hub)
    sut.append("a")
    sut.append("b")

    local_events: list[CollectionChangedMessage[str]] = []
    hub_messages: list[CollectionChangedMessage[str]] = []
    sut.on_collection_changed.subscribe(local_events.append)
    hub.messages.subscribe(hub_messages.append)  # type: ignore[arg-type]

    # ── Remove ────────────────────────────────────────────────────────────────
    sut.remove("a")

    assert len(local_events) == 1
    assert local_events[0].action == "remove"
    assert local_events[0].old_items == ("a",)

    assert len(hub_messages) == 1
    rm = hub_messages[0]
    assert isinstance(rm, CollectionChangedMessage)
    assert rm.action == "remove"
    assert rm.old_items == ("a",)

    # ── Replace ───────────────────────────────────────────────────────────────
    local_events.clear()
    hub_messages.clear()

    sut[0] = "b_replaced"

    assert len(local_events) == 1
    assert local_events[0].action == "replace"
    assert local_events[0].new_items == ("b_replaced",)
    assert local_events[0].old_items == ("b",)

    assert len(hub_messages) == 1
    rp = hub_messages[0]
    assert isinstance(rp, CollectionChangedMessage)
    assert rp.action == "replace"
    assert rp.new_items == ("b_replaced",)
    assert rp.old_items == ("b",)


# ---------------------------------------------------------------------------
# COL-003 — null-hub fallback
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-003")
def test_COL_003_null_hub_fallback_no_publication_no_error() -> None:
    """COL-003: Null-hub fallback — no hub means no publication, no error."""
    sut: ServicedObservableCollection[int] = ServicedObservableCollection(hub=None)

    local_events: list[CollectionChangedMessage[int]] = []
    sut.on_collection_changed.subscribe(local_events.append)

    # All mutations must not raise
    sut.append(1)
    sut.append(2)
    sut.remove(1)
    sut[0] = 99
    sut.clear()

    # Local events fired for each of the 5 mutations
    assert len(local_events) == 5


# ---------------------------------------------------------------------------
# COL-004 — fires on caller thread, no marshal
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-004")
def test_COL_004_fires_on_caller_thread_no_marshal() -> None:
    """COL-004: ServicedObservableCollection fires hub message on the caller thread."""
    hub: MessageHub[CollectionChangedMessage[int]] = MessageHub()
    sut: ServicedObservableCollection[int] = ServicedObservableCollection(name="sut", hub=hub)

    caller_tid = threading.current_thread().ident
    captured_tid: list[int | None] = []

    hub.messages.subscribe(lambda _: captured_tid.append(threading.current_thread().ident))  # type: ignore[arg-type]

    sut.append(42)

    assert len(captured_tid) == 1
    assert captured_tid[0] == caller_tid
