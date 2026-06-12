"""Conformance tests: LIFE-001..013.

LIFE-005, LIFE-006, LIFE-011 are implemented directly here and drive real VM
instances (a maintenance audit found the earlier validator-only versions
could not fail if ``construct()`` stopped routing through ``require``).

LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 require richer harnesses
and are therefore delegated to test_component_vm.py / test_composite_vm.py.
The delegated test bodies just import the implementing test function and call
it — earlier scaffolding wrapped these in ``pytest.importorskip`` while the
modules were being phased in, but as of v2.0 every dependent module ships in
``vmx`` and the importorskip would silently mask a real packaging breakage.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.conformance.fixtures.loader import load
from vmx.components.builders import ComponentVMBuilder
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import is_legal


def _build_vm(
    on_construct: Callable[[], None] | None = None,
    on_destruct: Callable[[], None] | None = None,
) -> object:
    builder = ComponentVMBuilder().name("life-vm").with_null_services()
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    if on_destruct is not None:
        builder = builder.on_destruct(on_destruct)
    return builder.build()


def _invoke(vm: object, op: str) -> StatusTransitionError | None:
    try:
        getattr(vm, op)()
    except StatusTransitionError as exc:
        return exc
    return None


def _drive_transition(
    frm: ConstructionStatus, op: str
) -> tuple[StatusTransitionError | None, ConstructionStatus]:
    """Bring a freshly-built VM to *frm*, invoke *op*, return (error, final).

    Mid-transition states (CONSTRUCTING / DESTRUCTING) are reached via the
    builder's lifecycle hooks, which run while the transition is in flight
    (the catalog's "controllable hook" allowance).
    """
    captured: dict[str, StatusTransitionError | None] = {}

    if frm is ConstructionStatus.CONSTRUCTING:
        cell: list[object] = []
        vm = _build_vm(on_construct=lambda: captured.update(error=_invoke(cell[0], op)))
        cell.append(vm)
        vm.construct()  # type: ignore[attr-defined]
        return captured["error"], vm.status  # type: ignore[attr-defined]

    if frm is ConstructionStatus.DESTRUCTING:
        cell = []
        vm = _build_vm(on_destruct=lambda: captured.update(error=_invoke(cell[0], op)))
        cell.append(vm)
        vm.construct()  # type: ignore[attr-defined]
        vm.destruct()  # type: ignore[attr-defined]
        return captured["error"], vm.status  # type: ignore[attr-defined]

    vm = _build_vm()
    if frm is ConstructionStatus.CONSTRUCTED:
        vm.construct()  # type: ignore[attr-defined]
    elif frm is ConstructionStatus.DISPOSED:
        vm.dispose()  # type: ignore[attr-defined]
    # DESTRUCTED is the freshly-built state.
    return _invoke(vm, op), vm.status  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# LIFE-005 — construct() from Disposed raises StatusTransitionError
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-005")
def test_LIFE_005_construct_from_disposed_raises() -> None:
    vm = _build_vm()
    vm.dispose()  # type: ignore[attr-defined]
    with pytest.raises(StatusTransitionError) as exc_info:
        vm.construct()  # type: ignore[attr-defined]
    assert "Disposed" in str(exc_info.value)
    assert "construct" in str(exc_info.value)


# ---------------------------------------------------------------------------
# LIFE-006 — destruct() from Disposed raises StatusTransitionError
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-006")
def test_LIFE_006_destruct_from_disposed_raises() -> None:
    vm = _build_vm()
    vm.dispose()  # type: ignore[attr-defined]
    with pytest.raises(StatusTransitionError) as exc_info:
        vm.destruct()  # type: ignore[attr-defined]
    assert "Disposed" in str(exc_info.value)
    assert "destruct" in str(exc_info.value)


# ---------------------------------------------------------------------------
# LIFE-011 — VM transitions match the full fixture table
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-011")
def test_LIFE_011_vm_transitions_match_fixture_table() -> None:
    fixture = load("lifecycle-transitions.json")
    for row in fixture["transitions"]:
        frm = ConstructionStatus[row["from"].upper()]
        op: str = row["via"]
        expected_legal: bool = row["legal"]

        # Validator-level agreement (fast feedback on table drift).
        assert is_legal(frm, op) == expected_legal, f"is_legal mismatch for row {row}"

        # Drive a real VM through the row.
        error, final = _drive_transition(frm, op)
        if expected_legal:
            assert error is None, f"row {row}: unexpectedly raised {error!r}"
            expected_final = ConstructionStatus[row["to_final"].upper()]
            assert final is expected_final, (
                f"row {row}: final state {final!r}, expected {expected_final!r}"
            )
        else:
            assert isinstance(error, StatusTransitionError), (
                f"row {row}: expected StatusTransitionError, got {error!r}"
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
