"""Conformance tests: LIFE-001..012, LIFE-014.

Every LIFE id in this file drives a real ``ComponentVM`` instance and asserts
its own normative behavior directly — transition sequence, emitted
``ConstructionStatusChangedMessage``s, idempotency, and the ``is_constructed``
gating predicate. An earlier revision delegated most ids to one-line wrappers
that imported and called the implementing test in ``test_component_vm.py``;
those wrappers asserted nothing locally and double-counted each id (VMX-055),
so they were replaced with the self-contained bodies below.

LIFE-013 (the composite disposal cascade) is exercised by
``test_composite_vm.py::test_LIFE_013_dispose_cascades_depth_first`` — its
natural home is the composite suite, so it is not duplicated here.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.conformance.fixtures.loader import load
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import is_legal
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


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


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _build_hub_vm(name: str = "vm1") -> tuple[ComponentVM, MessageHub[object]]:
    """Build a ComponentVM wired to a real hub + immediate dispatcher.

    Unlike ``_build_vm`` (null services), this exposes the hub so a test can
    subscribe and assert on the exact sequence of emitted lifecycle messages.
    """
    hub = _hub()
    vm = ComponentVMBuilder().name(name).services(hub, _dispatcher()).build()
    return vm, hub


def _status_messages(hub: MessageHub[object]) -> list[ConstructionStatusChangedMessage]:
    """Subscribe to *hub* and accumulate ConstructionStatusChangedMessages in order."""
    collected: list[ConstructionStatusChangedMessage] = []
    hub.messages.subscribe(
        lambda m: collected.append(m) if isinstance(m, ConstructionStatusChangedMessage) else None
    )
    return collected


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
# LIFE-001 — construct() emits Constructing then Constructed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-001")
def test_LIFE_001_construct_emits_status_messages() -> None:
    """LIFE-001: construct() from Destructed emits exactly Constructing then Constructed."""
    vm, hub = _build_hub_vm()
    msgs = _status_messages(hub)
    vm.construct()

    statuses = [m.status for m in msgs]
    assert statuses == [
        ConstructionStatus.CONSTRUCTING,
        ConstructionStatus.CONSTRUCTED,
    ], f"Expected exactly [Constructing, Constructed]; got {statuses}"
    assert vm.is_constructed is True


# ---------------------------------------------------------------------------
# LIFE-002 — destruct() emits Destructing then Destructed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-002")
def test_LIFE_002_destruct_emits_status_messages() -> None:
    """LIFE-002: destruct() from Constructed emits exactly Destructing then Destructed."""
    vm, hub = _build_hub_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.destruct()

    statuses = [m.status for m in msgs]
    assert statuses == [
        ConstructionStatus.DESTRUCTING,
        ConstructionStatus.DESTRUCTED,
    ], f"Expected exactly [Destructing, Destructed]; got {statuses}"
    assert vm.is_constructed is False


# ---------------------------------------------------------------------------
# LIFE-003 — reconstruct() emits the full Destruct-then-Construct sequence
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-003")
def test_LIFE_003_reconstruct_emits_four_messages() -> None:
    """LIFE-003: reconstruct() emits Destructing, Destructed, Constructing, Constructed."""
    vm, hub = _build_hub_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.reconstruct()

    statuses = [m.status for m in msgs]
    assert statuses == [
        ConstructionStatus.DESTRUCTING,
        ConstructionStatus.DESTRUCTED,
        ConstructionStatus.CONSTRUCTING,
        ConstructionStatus.CONSTRUCTED,
    ], f"Expected the full reconstruct sequence; got {statuses}"


# ---------------------------------------------------------------------------
# LIFE-004 — dispose() reaches Disposed from any state, emitting one message
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-004")
def test_LIFE_004_dispose_reaches_disposed() -> None:
    """LIFE-004: dispose() reaches Disposed and emits one Disposed message."""
    vm, hub = _build_hub_vm()
    msgs = _status_messages(hub)
    vm.dispose()

    assert vm.status == ConstructionStatus.DISPOSED
    disposed = [m for m in msgs if m.status == ConstructionStatus.DISPOSED]
    assert len(disposed) == 1


# ---------------------------------------------------------------------------
# LIFE-007 — is_constructed == (status == Constructed) invariant
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-007")
def test_LIFE_007_is_constructed_invariant() -> None:
    """LIFE-007: is_constructed equals (status == Constructed) in every state."""
    vm, _ = _build_hub_vm()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    vm.construct()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    assert vm.is_constructed is True
    vm.destruct()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    assert vm.is_constructed is False
    vm.dispose()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)


# ---------------------------------------------------------------------------
# LIFE-008 — concurrent (re-entrant) operation while transitioning raises
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-008")
def test_LIFE_008_concurrent_operation_raises() -> None:
    """LIFE-008: re-invoking construct() while it is in-flight raises StatusTransitionError."""
    caught: list[StatusTransitionError] = []
    vm: ComponentVM | None = None

    def on_construct_cb() -> None:
        # This hook fires while the VM is still mid-construct (state Constructing,
        # not yet Constructed). Re-entering construct() must raise.
        assert vm is not None
        try:
            vm.construct()
        except StatusTransitionError as exc:
            caught.append(exc)

    vm = (
        ComponentVMBuilder()
        .name("vm-reentrant")
        .services(_hub(), _dispatcher())
        .on_construct(on_construct_cb)
        .build()
    )

    vm.construct()

    assert len(caught) == 1, (
        "Re-entrant construct() during the in-flight transition must raise StatusTransitionError"
    )


# ---------------------------------------------------------------------------
# LIFE-009 — construct() from Constructed is idempotent (no message)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-009")
def test_LIFE_009_construct_from_constructed_is_noop() -> None:
    """LIFE-009: construct() from Constructed emits no message and stays Constructed."""
    vm, hub = _build_hub_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.construct()  # no-op

    assert msgs == []
    assert vm.status == ConstructionStatus.CONSTRUCTED


# ---------------------------------------------------------------------------
# LIFE-010 — destruct() from Destructed is idempotent (no message)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-010")
def test_LIFE_010_destruct_from_destructed_is_noop() -> None:
    """LIFE-010: destruct() from Destructed emits no message and stays Destructed."""
    vm, hub = _build_hub_vm()
    msgs = _status_messages(hub)
    vm.destruct()  # no-op from the freshly-built Destructed state

    assert msgs == []
    assert vm.status == ConstructionStatus.DESTRUCTED


# ---------------------------------------------------------------------------
# LIFE-012 — dispose() from Disposed is idempotent (no message)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-012")
def test_LIFE_012_dispose_from_disposed_is_noop() -> None:
    """LIFE-012: dispose() from Disposed emits no message and stays Disposed."""
    vm, hub = _build_hub_vm()
    vm.dispose()
    msgs = _status_messages(hub)
    vm.dispose()  # no-op

    assert msgs == []
    assert vm.status == ConstructionStatus.DISPOSED


# ---------------------------------------------------------------------------
# LIFE-014 — a throwing construct/destruct hook rolls Status back (transactional)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LIFE-014")
def test_LIFE_014_throwing_hook_rolls_status_back() -> None:
    """LIFE-014: a throwing on_construct/on_destruct hook rolls Status back to the
    prior settled state (not wedged in the transient state) and leaves the VM
    recoverable (spec/02-lifecycle.md §2.5)."""
    flags = {"construct": True, "destruct": True}

    # ── construct: hook raises → rollback to Destructed, then recoverable ──
    def on_construct() -> None:
        if flags["construct"]:
            raise RuntimeError("construct hook failed")

    vm = (
        ComponentVMBuilder()
        .name("life-014")
        .services(_hub(), _dispatcher())
        .on_construct(on_construct)
        .build()
    )

    with pytest.raises(RuntimeError, match="construct hook failed"):
        vm.construct()
    # Rolled back — not wedged in CONSTRUCTING.
    assert vm.status == ConstructionStatus.DESTRUCTED
    # Recoverable — a non-throwing retry reaches CONSTRUCTED.
    flags["construct"] = False
    vm.construct()
    assert vm.status == ConstructionStatus.CONSTRUCTED

    # ── destruct: hook raises → rollback to Constructed, then recoverable ──
    def on_destruct() -> None:
        if flags["destruct"]:
            raise RuntimeError("destruct hook failed")

    vm2 = (
        ComponentVMBuilder()
        .name("life-014b")
        .services(_hub(), _dispatcher())
        .on_destruct(on_destruct)
        .build()
    )
    vm2.construct()
    assert vm2.status == ConstructionStatus.CONSTRUCTED

    with pytest.raises(RuntimeError, match="destruct hook failed"):
        vm2.destruct()
    # Rolled back — not wedged in DESTRUCTING.
    assert vm2.status == ConstructionStatus.CONSTRUCTED
    # Recoverable — a non-throwing retry reaches DESTRUCTED.
    flags["destruct"] = False
    vm2.destruct()
    assert vm2.status == ConstructionStatus.DESTRUCTED
