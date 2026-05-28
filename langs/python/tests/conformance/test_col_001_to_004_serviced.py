"""Conformance stubs: COL-001..COL-004 — ServicedObservableCollection[T].

Per spec/21-collections.md §2 and ADR-0024.
Implemented in Substage 1C.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# COL-001 — publish to hub after local event on add
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-001")
def test_COL_001_publishes_to_hub_after_local_event_on_add() -> None:
    """COL-001: ServicedObservableCollection publishes to hub after local CollectionChanged."""
    pytest.skip("COL-001 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-002 — publish on remove and replace
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-002")
def test_COL_002_publishes_on_remove_and_replace() -> None:
    """COL-002: ServicedObservableCollection publishes correct messages on remove and replace."""
    pytest.skip("COL-002 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-003 — null-hub fallback
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-003")
def test_COL_003_null_hub_fallback_no_publication_no_error() -> None:
    """COL-003: Null-hub fallback — no hub means no publication, no error."""
    pytest.skip("COL-003 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-004 — fires on caller thread, no marshal
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-004")
def test_COL_004_fires_on_caller_thread_no_marshal() -> None:
    """COL-004: ServicedObservableCollection fires hub message on the caller thread."""
    pytest.skip("COL-004 stub — implement in Substage 1C")
    raise NotImplementedError
