"""Conformance tests: LIFE-001..013.

LIFE-005, LIFE-006, LIFE-011 are implemented directly here (they only need the
transition validator and the fixture table — no VM instance required).

LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 require a concrete VM instance
and are therefore delegated to test_component_vm.py / test_composite_vm.py.
The delegated test bodies just import the implementing test function and call
it — earlier scaffolding wrapped these in ``pytest.importorskip`` while the
modules were being phased in, but as of v2.0 every dependent module ships in
``vmx`` and the importorskip would silently mask a real packaging breakage.
"""

from __future__ import annotations

import pytest

from tests.conformance.fixtures.loader import load
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import is_legal, require

# ---------------------------------------------------------------------------
# LIFE-005 — construct() from Disposed raises StatusTransitionError
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-005")
def test_LIFE_005_construct_from_disposed_raises() -> None:
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "construct")
    assert "Disposed" in str(exc_info.value)
    assert "construct" in str(exc_info.value)


# ---------------------------------------------------------------------------
# LIFE-006 — destruct() from Disposed raises StatusTransitionError
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-006")
def test_LIFE_006_destruct_from_disposed_raises() -> None:
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "destruct")
    assert "Disposed" in str(exc_info.value)
    assert "destruct" in str(exc_info.value)


# ---------------------------------------------------------------------------
# LIFE-011 — transition validator matches the full fixture table
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-011")
def test_LIFE_011_validator_matches_fixture_table() -> None:
    fixture = load("lifecycle-transitions.json")
    for row in fixture["transitions"]:
        frm = ConstructionStatus[row["from"].upper()]
        op: str = row["via"]
        expected_legal: bool = row["legal"]
        assert is_legal(frm, op) == expected_legal, (
            f"Mismatch for row {row}: is_legal returned {is_legal(frm, op)!r}, "
            f"expected {expected_legal!r}"
        )


# ---------------------------------------------------------------------------
# Delegated tests — require VM instances. Each delegated test forwards
# directly to its implementation in test_component_vm.py / test_composite_vm.py
# so the conformance-id-to-test mapping is one entry per file.
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-001")
def test_LIFE_001_delegated() -> None:
    """construct() emits ConstructionStatusChangedMessage for each state change."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_001_construct_emits_status_messages,
    )

    test_LIFE_001_construct_emits_status_messages()


@pytest.mark.conformance("LIFE-002")
def test_LIFE_002_delegated() -> None:
    """destruct() emits ConstructionStatusChangedMessage for each state change."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_002_destruct_emits_status_messages,
    )

    test_LIFE_002_destruct_emits_status_messages()


@pytest.mark.conformance("LIFE-003")
def test_LIFE_003_delegated() -> None:
    """reconstruct() emits four ConstructionStatusChangedMessages."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_003_reconstruct_emits_four_messages,
    )

    test_LIFE_003_reconstruct_emits_four_messages()


@pytest.mark.conformance("LIFE-004")
def test_LIFE_004_delegated() -> None:
    """dispose() transitions VM to Disposed."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_004_dispose_reaches_disposed,
    )

    test_LIFE_004_dispose_reaches_disposed()


@pytest.mark.conformance("LIFE-007")
def test_LIFE_007_delegated() -> None:
    """IsConstructed == (Status == Constructed) invariant."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_007_is_constructed_invariant,
    )

    test_LIFE_007_is_constructed_invariant()


@pytest.mark.conformance("LIFE-008")
def test_LIFE_008_delegated() -> None:
    """Concurrent operation while transitioning raises StatusTransitionError."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_008_concurrent_operation_raises,
    )

    test_LIFE_008_concurrent_operation_raises()


@pytest.mark.conformance("LIFE-009")
def test_LIFE_009_delegated() -> None:
    """construct() from Constructed is a no-op (idempotent, no message emitted)."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_009_construct_from_constructed_is_noop,
    )

    test_LIFE_009_construct_from_constructed_is_noop()


@pytest.mark.conformance("LIFE-010")
def test_LIFE_010_delegated() -> None:
    """destruct() from Destructed is a no-op (idempotent, no message emitted)."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_010_destruct_from_destructed_is_noop,
    )

    test_LIFE_010_destruct_from_destructed_is_noop()


@pytest.mark.conformance("LIFE-012")
def test_LIFE_012_delegated() -> None:
    """dispose() from Disposed is a no-op (idempotent, no message emitted)."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_LIFE_012_dispose_from_disposed_is_noop,
    )

    test_LIFE_012_dispose_from_disposed_is_noop()


@pytest.mark.conformance("LIFE-013")
def test_LIFE_013_delegated() -> None:
    """dispose() on parent disposes every child (disposal cascade)."""
    from tests.conformance.test_composite_vm import (  # type: ignore[import]
        test_LIFE_013_dispose_cascade,
    )

    test_LIFE_013_dispose_cascade()
