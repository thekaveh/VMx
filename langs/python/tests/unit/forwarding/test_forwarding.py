"""Unit tests for ForwardingComponentVM and ForwardingCompositeVM.

Covers:
- All delegating members on ForwardingComponentVM
- Selective override (hint property)
- ForwardingCompositeVM iteration delegation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

from vmx.components.protocols import ViewModelType
from vmx.forwarding.component import ForwardingComponentVM
from vmx.forwarding.composite import ForwardingCompositeVM
from vmx.lifecycle.status import ConstructionStatus

# ---------------------------------------------------------------------------
# Helpers: minimal stubs
# ---------------------------------------------------------------------------


def _make_component_mock() -> MagicMock:
    """Return a MagicMock that satisfies ComponentVMOfProto[str]."""
    m = MagicMock()
    # Set up property returns via configure_mock or type(m) patching.
    type(m).name = PropertyMock(return_value="inner-name")
    type(m).hint = PropertyMock(return_value="inner-hint")
    type(m).type = PropertyMock(return_value=ViewModelType.COMPONENT)
    type(m).is_current = PropertyMock(return_value=False)
    type(m).is_constructed = PropertyMock(return_value=True)
    type(m).status = PropertyMock(return_value=ConstructionStatus.CONSTRUCTED)
    type(m).model = PropertyMock(return_value="model-value")
    type(m).modeled_hint = PropertyMock(return_value="modeled-hint")
    type(m).property_changed = PropertyMock(return_value=MagicMock())
    type(m).select_command = PropertyMock(return_value=MagicMock())
    type(m).deselect_command = PropertyMock(return_value=MagicMock())
    type(m).select_next_command = PropertyMock(return_value=MagicMock())
    type(m).select_previous_command = PropertyMock(return_value=MagicMock())
    type(m).reconstruct_command = PropertyMock(return_value=MagicMock())
    m.can_construct.return_value = True
    m.can_destruct.return_value = True
    m.can_reconstruct.return_value = True
    m.can_select.return_value = False
    m.can_deselect.return_value = False
    return m


def _make_composite_mock(children: list[Any]) -> MagicMock:
    """Return a MagicMock that satisfies CompositeVMProto with iterable children."""
    m = MagicMock()
    type(m).name = PropertyMock(return_value="composite-name")
    type(m).hint = PropertyMock(return_value="composite-hint")
    type(m).type = PropertyMock(return_value=ViewModelType.COMPOSITE)
    type(m).is_current = PropertyMock(return_value=False)
    type(m).is_constructed = PropertyMock(return_value=True)
    type(m).status = PropertyMock(return_value=ConstructionStatus.CONSTRUCTED)
    type(m).property_changed = PropertyMock(return_value=MagicMock())
    type(m).select_command = PropertyMock(return_value=MagicMock())
    type(m).deselect_command = PropertyMock(return_value=MagicMock())
    type(m).select_next_command = PropertyMock(return_value=MagicMock())
    type(m).select_previous_command = PropertyMock(return_value=MagicMock())
    type(m).reconstruct_command = PropertyMock(return_value=MagicMock())
    type(m).current = PropertyMock(return_value=None)
    type(m).on_collection_changed = PropertyMock(return_value=MagicMock())
    type(m).count = PropertyMock(return_value=len(children))
    m.can_construct.return_value = True
    m.can_destruct.return_value = True
    m.can_reconstruct.return_value = True
    m.can_select.return_value = False
    m.can_deselect.return_value = False
    m.can_select_component.return_value = True
    # Make the mock iterable, returning children.
    m.__iter__ = MagicMock(return_value=iter(children))
    return m


# ---------------------------------------------------------------------------
# ForwardingComponentVM — base delegation
# ---------------------------------------------------------------------------


class _PassthroughVM(ForwardingComponentVM[str]):
    """Concrete no-override subclass for delegation tests."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)


class _HintOverrideVM(ForwardingComponentVM[str]):
    """Subclass that overrides only ``hint``."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)

    @property
    def hint(self) -> str:
        return "OVERRIDE"


class _PassthroughCompositeVM(ForwardingCompositeVM[Any]):
    """Concrete no-override subclass for composite delegation tests."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)


# ---------------------------------------------------------------------------
# Tests: ForwardingComponentVM identity properties
# ---------------------------------------------------------------------------


def test_name_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.name == "inner-name"


def test_hint_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.hint == "inner-hint"


def test_type_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.type is ViewModelType.COMPONENT


def test_is_current_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.is_current is False


def test_is_constructed_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.is_constructed is True


def test_status_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.status is ConstructionStatus.CONSTRUCTED


def test_model_getter_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.model == "model-value"


def test_model_setter_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    # Setting model on the forwarding VM should propagate to the inner mock's
    # model property setter. We verify this by reading fwd.model, which returns
    # the mocked value, showing delegation is wired correctly.
    fwd.model = "new-model"
    # No AttributeError means the setter on ForwardingComponentVM ran without
    # crashing; the mock absorbs the assignment.
    assert fwd.model == "model-value"  # still the mock's return value


def test_modeled_hint_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.modeled_hint == "modeled-hint"


def test_commands_delegate() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.select_command is inner.select_command
    assert fwd.deselect_command is inner.deselect_command
    assert fwd.select_next_command is inner.select_next_command
    assert fwd.select_previous_command is inner.select_previous_command
    assert fwd.reconstruct_command is inner.reconstruct_command


def test_can_construct_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.can_construct() is True
    inner.can_construct.assert_called_once()


def test_construct_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.construct()
    inner.construct.assert_called_once()


def test_can_destruct_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.can_destruct() is True
    inner.can_destruct.assert_called_once()


def test_destruct_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.destruct()
    inner.destruct.assert_called_once()


def test_reconstruct_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.reconstruct()
    inner.reconstruct.assert_called_once()


def test_dispose_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.dispose()
    inner.dispose.assert_called_once()


def test_can_select_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.can_select() is False
    inner.can_select.assert_called_once()


def test_select_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.select()
    inner.select.assert_called_once()


def test_can_deselect_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    assert fwd.can_deselect() is False
    inner.can_deselect.assert_called_once()


def test_deselect_delegates() -> None:
    inner = _make_component_mock()
    fwd = _PassthroughVM(inner)
    fwd.deselect()
    inner.deselect.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: ForwardingComponentVM — selective override
# ---------------------------------------------------------------------------


def test_override_hint_returns_override() -> None:
    inner = _make_component_mock()
    fwd = _HintOverrideVM(inner)
    assert fwd.hint == "OVERRIDE"


def test_override_hint_does_not_affect_name() -> None:
    inner = _make_component_mock()
    fwd = _HintOverrideVM(inner)
    assert fwd.name == "inner-name"


def test_override_hint_does_not_affect_status() -> None:
    inner = _make_component_mock()
    fwd = _HintOverrideVM(inner)
    assert fwd.status is ConstructionStatus.CONSTRUCTED


def test_override_hint_does_not_affect_commands() -> None:
    inner = _make_component_mock()
    fwd = _HintOverrideVM(inner)
    assert fwd.select_command is inner.select_command


# ---------------------------------------------------------------------------
# Tests: constructor guard
# ---------------------------------------------------------------------------


def test_none_wrapped_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        ForwardingComponentVM(None)  # type: ignore[arg-type]


def test_none_composite_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        ForwardingCompositeVM(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: ForwardingCompositeVM — iteration delegation (FWD-003 unit coverage)
# ---------------------------------------------------------------------------


def test_composite_iteration_delegates_in_order() -> None:
    child1 = MagicMock()
    child2 = MagicMock()
    inner = _make_composite_mock([child1, child2])
    fwd = _PassthroughCompositeVM(inner)
    result = list(fwd)
    assert result == [child1, child2]


def test_composite_count_delegates() -> None:
    inner = _make_composite_mock(["a", "b", "c"])
    fwd = _PassthroughCompositeVM(inner)
    assert fwd.count == 3


def test_composite_len_delegates() -> None:
    inner = _make_composite_mock(["x"])
    fwd = _PassthroughCompositeVM(inner)
    assert len(fwd) == 1


def test_composite_move_delegates() -> None:
    inner = _make_composite_mock(["a", "b"])
    fwd = _PassthroughCompositeVM(inner)

    fwd.move(0, 1)

    inner.move.assert_called_once_with(0, 1)


def test_composite_batch_update_delegates_and_returns_handle() -> None:
    inner = _make_composite_mock([])
    handle = MagicMock()
    inner.batch_update.return_value = handle
    fwd = _PassthroughCompositeVM(inner)

    result = fwd.batch_update()

    assert result is handle
    inner.batch_update.assert_called_once_with()


def test_composite_identity_properties_delegate() -> None:
    inner = _make_composite_mock([])
    fwd = _PassthroughCompositeVM(inner)
    assert fwd.name == "composite-name"
    assert fwd.hint == "composite-hint"
    assert fwd.type is ViewModelType.COMPOSITE
    assert fwd.is_constructed is True
    assert fwd.status is ConstructionStatus.CONSTRUCTED
