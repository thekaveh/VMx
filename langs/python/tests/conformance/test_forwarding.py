"""Conformance tests: FWD-001..003.

FWD-001: ForwardingComponentVM with no overrides delegates every member to wrapped.
FWD-002: Selective override of ``hint`` returns "OVERRIDE"; all others still delegate.
FWD-003: ForwardingCompositeVM iteration yields wrapped's children in order.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

from vmx.components.builders import ComponentVMOfBuilder
from vmx.components.protocols import ViewModelType
from vmx.composites.builders import CompositeVMBuilder
from vmx.forwarding.component import ForwardingComponentVM
from vmx.forwarding.composite import ForwardingCompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component_inner() -> MagicMock:
    """Minimal ComponentVMOfProto[str] mock with deterministic values."""
    m = MagicMock()
    type(m).name = PropertyMock(return_value="inner-name")
    type(m).hint = PropertyMock(return_value="inner-hint")
    type(m).type = PropertyMock(return_value=ViewModelType.COMPONENT)
    type(m).is_current = PropertyMock(return_value=False)
    type(m).is_constructed = PropertyMock(return_value=True)
    type(m).status = PropertyMock(return_value=ConstructionStatus.CONSTRUCTED)
    type(m).model = PropertyMock(return_value="inner-model")
    type(m).modeled_hint = PropertyMock(return_value="inner-modeled-hint")
    type(m).property_changed = PropertyMock(return_value=MagicMock())
    _cmd = MagicMock()
    type(m).select_command = PropertyMock(return_value=_cmd)
    type(m).deselect_command = PropertyMock(return_value=_cmd)
    type(m).select_next_command = PropertyMock(return_value=_cmd)
    type(m).select_previous_command = PropertyMock(return_value=_cmd)
    type(m).reconstruct_command = PropertyMock(return_value=_cmd)
    m.can_construct.return_value = True
    m.can_destruct.return_value = True
    m.can_reconstruct.return_value = False
    m.can_select.return_value = True
    m.can_deselect.return_value = False
    return m


def _make_composite_inner(children: list[Any]) -> MagicMock:
    """Minimal CompositeVMProto[Any] mock with fixed children list."""
    m = MagicMock()
    type(m).name = PropertyMock(return_value="comp-name")
    type(m).hint = PropertyMock(return_value="comp-hint")
    type(m).type = PropertyMock(return_value=ViewModelType.COMPOSITE)
    type(m).is_current = PropertyMock(return_value=False)
    type(m).is_constructed = PropertyMock(return_value=True)
    type(m).status = PropertyMock(return_value=ConstructionStatus.CONSTRUCTED)
    type(m).property_changed = PropertyMock(return_value=MagicMock())
    _cmd = MagicMock()
    type(m).select_command = PropertyMock(return_value=_cmd)
    type(m).deselect_command = PropertyMock(return_value=_cmd)
    type(m).select_next_command = PropertyMock(return_value=_cmd)
    type(m).select_previous_command = PropertyMock(return_value=_cmd)
    type(m).reconstruct_command = PropertyMock(return_value=_cmd)
    type(m).current = PropertyMock(return_value=None)
    type(m).on_collection_changed = PropertyMock(return_value=MagicMock())
    type(m).count = PropertyMock(return_value=len(children))
    m.can_construct.return_value = True
    m.can_destruct.return_value = True
    m.can_reconstruct.return_value = False
    m.can_select.return_value = False
    m.can_deselect.return_value = False
    m.can_select_component.return_value = True
    m.__iter__ = MagicMock(return_value=iter(children))
    return m


# ---------------------------------------------------------------------------
# FWD-001: concrete no-override subclass delegates every member to inner
# ---------------------------------------------------------------------------


class _NoOverrideVM(ForwardingComponentVM[str]):
    def __init__(self, inner: Any) -> None:
        super().__init__(inner)


@pytest.mark.conformance("FWD-001")
def test_FWD_001_no_override_delegates_every_member() -> None:
    """Every public member of the forwarding VM reads/invokes the wrapped VM."""
    inner = _make_component_inner()
    fwd = _NoOverrideVM(inner)

    # ── Identity ──────────────────────────────────────────────────────────────
    assert fwd.name == inner.name
    assert fwd.hint == inner.hint
    assert fwd.type is inner.type

    # ── State ─────────────────────────────────────────────────────────────────
    assert fwd.is_current == inner.is_current
    assert fwd.is_constructed == inner.is_constructed
    assert fwd.status is inner.status

    # ── Model ─────────────────────────────────────────────────────────────────
    assert fwd.model == inner.model
    assert fwd.modeled_hint == inner.modeled_hint

    # ── Commands (reference equality — same object from inner) ────────────────
    assert fwd.select_command is inner.select_command
    assert fwd.deselect_command is inner.deselect_command
    assert fwd.select_next_command is inner.select_next_command
    assert fwd.select_previous_command is inner.select_previous_command
    assert fwd.reconstruct_command is inner.reconstruct_command

    # ── Lifecycle predicates ──────────────────────────────────────────────────
    assert fwd.can_construct() == inner.can_construct()
    assert fwd.can_destruct() == inner.can_destruct()
    assert fwd.can_reconstruct() == inner.can_reconstruct()

    # ── Lifecycle mutators call through to inner ──────────────────────────────
    fwd.construct()
    inner.construct.assert_called_once()

    fwd.destruct()
    inner.destruct.assert_called_once()

    fwd.reconstruct()
    inner.reconstruct.assert_called_once()

    fwd.dispose()
    inner.dispose.assert_called_once()

    # ── Selection predicates ──────────────────────────────────────────────────
    assert fwd.can_select() == inner.can_select()
    assert fwd.can_deselect() == inner.can_deselect()

    # ── Selection mutators ────────────────────────────────────────────────────
    fwd.select()
    inner.select.assert_called_once()

    fwd.deselect()
    inner.deselect.assert_called_once()


def test_forwarding_component_is_a_transparent_container_child() -> None:
    inner = ComponentVMOfBuilder[str]().name("inner").model("model").with_null_services().build()
    forwarding = ForwardingComponentVM(inner)
    composite = (
        CompositeVMBuilder[ForwardingComponentVM[str]]()
        .name("root")
        .services(inner.hub, RxDispatcher.immediate())
        .children(lambda: ())
        .build()
    )

    composite.add(forwarding)
    composite.construct()
    forwarding.select_command.execute()

    assert composite.current is forwarding
    assert forwarding.is_current
    assert inner.is_current


# ---------------------------------------------------------------------------
# FWD-002: selective override of ``hint`` returns "OVERRIDE"; others delegate
# ---------------------------------------------------------------------------


class _HintOverrideVM(ForwardingComponentVM[str]):
    """Subclass that overrides only ``hint`` to return a fixed string."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)

    @property
    def hint(self) -> str:
        return "OVERRIDE"


@pytest.mark.conformance("FWD-002")
def test_FWD_002_hint_override_returns_override_all_others_delegate() -> None:
    """Overriding hint returns 'OVERRIDE'; every other member still delegates."""
    inner = _make_component_inner()
    fwd = _HintOverrideVM(inner)

    # Overridden member.
    assert fwd.hint == "OVERRIDE"

    # All other members still delegate to inner.
    assert fwd.name == inner.name
    assert fwd.type is inner.type
    assert fwd.is_current == inner.is_current
    assert fwd.is_constructed == inner.is_constructed
    assert fwd.status is inner.status
    assert fwd.model == inner.model
    assert fwd.modeled_hint == inner.modeled_hint
    assert fwd.select_command is inner.select_command
    assert fwd.can_construct() == inner.can_construct()
    assert fwd.can_select() == inner.can_select()


# ---------------------------------------------------------------------------
# FWD-003: ForwardingCompositeVM iteration yields wrapped's children in order
# ---------------------------------------------------------------------------


class _NoOverrideCompositeVM(ForwardingCompositeVM[Any]):
    def __init__(self, inner: Any) -> None:
        super().__init__(inner)


@pytest.mark.conformance("FWD-003")
def test_FWD_003_forwarding_composite_iteration_yields_children_in_order() -> None:
    """Iterating the forwarding composite yields vm1, vm2 in order from wrapped."""
    vm1 = MagicMock(name="vm1")
    vm2 = MagicMock(name="vm2")
    inner = _make_composite_inner([vm1, vm2])
    fwd = _NoOverrideCompositeVM(inner)

    result = list(fwd)
    assert result == [vm1, vm2], f"Expected [vm1, vm2], got {result}"
    assert result[0] is vm1
    assert result[1] is vm2


def test_forwarding_composite_setitem_delegates_to_wrapped() -> None:
    """fwd[i] = value forwards to wrapped[i] = value (parity with C# this[int] setter)."""
    vm1 = MagicMock(name="vm1")
    vm2 = MagicMock(name="vm2")
    vm3 = MagicMock(name="vm3")
    inner = _make_composite_inner([vm1, vm2])
    fwd = _NoOverrideCompositeVM(inner)

    fwd[1] = vm3

    inner.__setitem__.assert_called_once_with(1, vm3)
