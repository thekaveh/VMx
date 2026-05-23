"""Conformance tests: PROP-001..004.

These tests require a concrete ComponentVM implementation (Task 6).
Until that module is available they skip via ``pytest.importorskip``, which
matches the same pattern used in test_lifecycle.py for delegated tests.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# PROP-001 — PropertyChangedMessage emitted only on real changes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-001")
def test_PROP_001_delegated() -> None:
    """PropertyChangedMessage is emitted when a property value changes."""
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_001_property_changed_emitted_on_change,
    )

    test_PROP_001_property_changed_emitted_on_change()


# ---------------------------------------------------------------------------
# PROP-002 — No message emitted on same-value set
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-002")
def test_PROP_002_delegated() -> None:
    """No PropertyChangedMessage emitted when setting the same value."""
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_002_no_message_on_same_value,
    )

    test_PROP_002_no_message_on_same_value()


# ---------------------------------------------------------------------------
# PROP-003 — sender identity is correct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-003")
def test_PROP_003_delegated() -> None:
    """PropertyChangedMessage carries the correct sender instance."""
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_003_sender_identity,
    )

    test_PROP_003_sender_identity()


# ---------------------------------------------------------------------------
# PROP-004 — property name and sender name correctness
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-004")
def test_PROP_004_delegated() -> None:
    """PropertyChangedMessage carries correct property_name and sender_name."""
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_004_property_name_and_sender_name,
    )

    test_PROP_004_property_name_and_sender_name()
